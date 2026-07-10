"""Production DeviceGateway over the NanoC6/H2 coordinator UART link.

Implements the protocol proven on hardware in experiments/zigbee_probe
(Gate 2+3 pass on both ESP32-H2 and NanoC6, 2026-07-09): CRC32+JSON line
envelope, op-based commands (ping / permit_join / on_off / read_attr /
enable_reporting / remove_device), request_id as the only correlation id,
and spontaneous coordinator events (device_joined, attribute_report, ...).

Division of responsibility (docs/hardware_audit.md): the coordinator is a
stateless execution arm; this adapter owns the device registry, keyed by
the stable ieee address. short_addr changes on rejoin, so the registry is
healed from every device_joined event, not only during pairing.

Fully event-driven — no polling sleeps anywhere:

  - Inbound: the device entry point runs one reader task
    (``asyncio.StreamReader(uart).readline()``) and hands every line to
    ``process_line()``; tests call it directly.
  - Outbound: ``send()`` registers an ``asyncio.Event`` per request_id and
    awaits it; ``process_line()`` sets it the moment the matching ack (or
    error) frame arrives. Latency is the radio round-trip, nothing more,
    and the shared loop stays free while a command is in flight.
  - Circuit breaker: consecutive ack timeouts mark the coordinator down
    and commands fail fast (status "error", no UART wait) until any valid
    inbound frame proves the link again; ``watchdog()`` pings to re-probe.
  - Toggle uses the live reported state when known (one round-trip) and
    falls back to read_attr when it is not.
  - ``wait_for_report()`` exposes observed-state confirmation: the next
    attribute_report is the device's own word that the state changed.
"""

try:
    import ujson as json
except ImportError:
    import json

import asyncio

try:
    from time import ticks_add, ticks_diff, ticks_ms
except ImportError:  # CPython
    import time as _time

    def ticks_ms():
        return int(_time.monotonic() * 1000)

    def ticks_add(t, delta):
        return t + delta

    def ticks_diff(a, b):
        return a - b

from ..ports.device_gateway import DeviceGateway
from .uart_codec import decode as uart_decode
from .uart_codec import encode as uart_encode

# Acks measured well under 500ms on hardware; 1500ms already means the
# command is lost (coordinator restarts take longer than any retry helps).
_DEFAULT_ACK_TIMEOUT_MS = 1500
_BREAKER_THRESHOLD = 2          # consecutive timeouts before failing fast
_WATCHDOG_UP_MS = 30000         # heartbeat ping interval while link is up
_WATCHDOG_DOWN_MS = 2000        # re-probe interval while link is down


class ZigbeeGateway(DeviceGateway):
    def __init__(self, uart, repository, registry_path=None,
                 ack_timeout_ms=_DEFAULT_ACK_TIMEOUT_MS, log=print):
        self._uart = uart
        self._repo = repository
        self._registry_path = registry_path
        self._ack_timeout_ms = ack_timeout_ms
        self._log = log
        self._seq = 0
        # rid -> [asyncio.Event, reply-or-None]
        self._pending = {}
        # ieee -> {"short_addr": str, "endpoint": int, "reporting": bool}
        self._registry = self._load_registry()
        # ieee -> bool, from attribute_report and read_attr acks
        self._states = {}
        self._state_ms = {}
        # ieee -> [asyncio.Event, ...] — observed-state waiters
        self._state_waiters = {}
        # circuit breaker — moved ONLY by ping outcomes: a device that
        # dropped off the mesh times out too, and must not be mistaken
        # for a dead coordinator link.
        self._ping_timeouts = 0
        self._down = False
        self._probe_inflight = False
        # ieee -> True when a command to the device timed out while the
        # coordinator link was fine (classic stale-short_addr rejoin);
        # cleared by any report/rejoin from the device.
        self._suspect = {}
        # coordinator liveness, learned from boot/ping/network_formed
        self.info = {"network_up": None, "firmware_version": None,
                     "target": None}

    # ── registry persistence (hub owns the registry) ──────────────────

    def _load_registry(self):
        if not self._registry_path:
            return {}
        try:
            with open(self._registry_path) as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_registry(self):
        if not self._registry_path:
            return
        try:
            with open(self._registry_path, "w") as f:
                json.dump(self._registry, f)
        except OSError as exc:
            self._log("zigbee registry save failed:", exc)

    # ── public views for status/UI ─────────────────────────────────────

    def devices(self):
        """Registry + last known on/off state, keyed by ieee."""
        out = {}
        for ieee, entry in self._registry.items():
            item = dict(entry)
            if ieee in self._states:
                item["on_off"] = self._states[ieee]
                item["state_age_ms"] = ticks_diff(
                    ticks_ms(), self._state_ms[ieee])
            if self._suspect.get(ieee):
                item["unreachable"] = True
            out[ieee] = item
        return out

    def status_info(self):
        info = {"gateway": "zigbee", "devices": len(self._registry),
                "link_down": self._down}
        info.update(self.info)
        return info

    # ── inbound: one line at a time, from the reader task ──────────────

    def process_line(self, line):
        """Decode and handle one inbound UART line; safe to call with
        console noise (skipped). Returns True when a frame was handled."""
        if isinstance(line, (bytes, bytearray)):
            line = bytes(line).strip()
            if not line:
                return False
        try:
            msg = uart_decode(line)
        except ValueError:
            return False

        # Any valid frame proves the link — reset the breaker.
        self._ping_timeouts = 0
        if self._down:
            self._down = False
            self._log("zigbee link restored")

        rid = msg.get("request_id")
        if rid and rid in self._pending and \
                msg.get("type") in ("ack", "error"):
            slot = self._pending[rid]
            slot[1] = msg
            slot[0].set()

        self._handle_async(msg)
        return True

    def _handle_async(self, msg):
        mtype = msg.get("type")
        op = msg.get("op")
        payload = msg.get("payload") or {}

        if mtype == "event":
            if op == "device_joined":
                self._on_device_joined(payload)
            elif op == "attribute_report":
                self._on_state(payload)
            elif op == "reporting_configured":
                ieee = self._ieee_for_short(payload.get("short_addr"))
                if ieee:
                    self._registry[ieee]["reporting"] = True
                    self._save_registry()
            elif op in ("boot", "network_formed"):
                self.info["network_up"] = True
                if payload.get("firmware_version"):
                    self.info["firmware_version"] = payload["firmware_version"]
                if payload.get("target"):
                    self.info["target"] = payload["target"]
        elif mtype == "ack":
            if op == "ping":
                self.info["network_up"] = bool(payload.get("network_up"))
                self.info["firmware_version"] = payload.get("firmware_version")
                self.info["target"] = payload.get("target")
            elif op == "read_attr" and "on_off" in payload:
                # stray/late read ack still carries usable state
                self._on_state(payload)

    def _on_device_joined(self, payload):
        ieee = payload.get("ieee_addr")
        short = payload.get("short_addr")
        if not (ieee and short):
            return
        entry = self._registry.get(ieee)
        first_join = entry is None
        if first_join:
            entry = {"reporting": False}
            self._registry[ieee] = entry
        entry["short_addr"] = short
        entry["endpoint"] = payload.get("endpoint", entry.get("endpoint", 1))
        self._suspect.pop(ieee, None)  # fresh address — reachable again
        self._save_registry()
        self._log("zigbee device", "joined:" if first_join else "rejoined:",
                  ieee, short)
        # Fire and forget: the reporting_configured event flips the flag.
        # Reporting is cheap to (re)request and idempotent.
        self._write_cmd("enable_reporting",
                        {"short_addr": short, "endpoint": entry["endpoint"]})

    def _on_state(self, payload):
        ieee = self._ieee_for_short(payload.get("short_addr"))
        if not ieee or "on_off" not in payload:
            return
        self._states[ieee] = bool(payload["on_off"])
        self._state_ms[ieee] = ticks_ms()
        self._suspect.pop(ieee, None)  # it spoke — clearly reachable
        for evt in self._state_waiters.pop(ieee, []):
            evt.set()

    def _ieee_for_short(self, short):
        for ieee, entry in self._registry.items():
            if entry.get("short_addr") == short:
                return ieee
        return None

    # ── observed-state confirmation (ACK level 4) ──────────────────────

    async def wait_for_report(self, ieee, expect, timeout_ms):
        """Await attribute_report(s) from ``ieee`` until one says
        ``expect`` or the timeout passes. Returns a confirmation dict —
        this is the device's own word, not an ack echo.

        The current state is checked before each wait: the report often
        lands in the same burst as the command's ack, i.e. before the
        caller starts waiting, and must still count."""
        deadline = ticks_add(ticks_ms(), timeout_ms)
        while True:
            if self._states.get(ieee) == expect:
                return {"confirmed": True, "observed": expect}
            remaining = ticks_diff(deadline, ticks_ms())
            if remaining <= 0:
                return {"confirmed": False,
                        "observed": self._states.get(ieee)}
            evt = asyncio.Event()
            self._state_waiters.setdefault(ieee, []).append(evt)
            try:
                await asyncio.wait_for(evt.wait(), remaining / 1000)
            except asyncio.TimeoutError:
                waiters = self._state_waiters.get(ieee, [])
                if evt in waiters:
                    waiters.remove(evt)
                return {"confirmed": False,
                        "observed": self._states.get(ieee)}

    # ── outbound: commands with ack correlation ────────────────────────

    def _next_rid(self, prefix):
        self._seq += 1
        return "{}-{}".format(prefix, self._seq)

    def _write_cmd(self, op, payload, rid=None):
        if rid is None:
            rid = self._next_rid(op)
        msg = {"version": 1, "type": "command", "op": op, "request_id": rid}
        if payload:
            msg["payload"] = payload
        self._uart.write(uart_encode(msg))
        return rid

    async def _command(self, op, payload, rid=None, timeout_ms=None):
        if self._down:
            return {"status": "error", "error": "coordinator_down",
                    "command_id": rid or op}
        if rid is None:
            rid = self._next_rid(op)
        evt = asyncio.Event()
        self._pending[rid] = [evt, None]
        self._write_cmd(op, payload, rid)
        try:
            await asyncio.wait_for(
                evt.wait(),
                (timeout_ms or self._ack_timeout_ms) / 1000)
        except asyncio.TimeoutError:
            self._pending.pop(rid, None)
            if op == "ping":
                self._ping_timeouts += 1
                if self._ping_timeouts >= _BREAKER_THRESHOLD \
                        and not self._down:
                    self._down = True
                    self._log("zigbee link down (no acks) - failing fast")
            else:
                # A device command timing out is ambiguous: dead link or
                # dead device. Let a ping decide — only its verdict moves
                # the breaker.
                self._probe_link()
            return {"status": "timeout", "command_id": rid}
        reply = self._pending.pop(rid)[1]
        if reply.get("type") == "error":
            code = (reply.get("payload") or {}).get("code",
                                                    "coordinator_error")
            return {"status": "error", "error": code, "command_id": rid}
        return {"status": "sent_to_zigbee", "command_id": rid,
                "reply": reply.get("payload") or {}}

    def _probe_link(self):
        """Fire one background ping to classify a command timeout. At most
        one probe in flight — a burst of timeouts must not ping-storm."""
        if self._probe_inflight or self._down:
            return

        async def probe():
            try:
                await self.ping()
            finally:
                self._probe_inflight = False

        self._probe_inflight = True
        try:
            asyncio.create_task(probe())
        except Exception:
            self._probe_inflight = False

    async def watchdog(self):
        """Heartbeat task: slow pings while the link is up, fast re-probes
        while it is down. The ping's ack (like any inbound frame) clears
        the breaker."""
        while True:
            await self.ping()
            await asyncio.sleep(
                (_WATCHDOG_DOWN_MS if self._down else _WATCHDOG_UP_MS)
                / 1000)

    # ── DeviceGateway contract ─────────────────────────────────────────

    async def send(self, event):
        """Deliver one planner/manual event. Never raises on delivery
        problems — returns a retryable status instead (Executor decides)."""
        target_type = event.get("target_type")
        target_id = event.get("target_id")
        action = event.get("action_type")
        event_id = event.get("event_id", "")

        try:
            targets = self._resolve_targets(target_type, target_id)
        except ValueError as exc:
            return {"status": "error", "error": str(exc),
                    "command_id": event_id}

        results = []
        for n, (ieee, short, zcl_ep) in enumerate(targets):
            rid = "{}-{}".format(event_id, n) if len(targets) > 1 else event_id
            if action == "toggle":
                result = await self._toggle(ieee, short, zcl_ep, rid)
            else:
                result = await self._command(
                    "on_off",
                    {"state": action, "short_addr": short,
                     "endpoint": zcl_ep},
                    rid=rid)
            if result["status"] == "timeout" and not self._down:
                # Coordinator link looks fine but this device is silent —
                # the classic stale short_addr after an unseen rejoin.
                self._suspect[ieee] = True
            results.append(result)

        worst = _worst_status(results)
        outcome = {"status": worst, "command_id": event_id}
        errors = [r.get("error") for r in results if r.get("error")]
        if errors:
            outcome["error"] = "; ".join(errors)
        return outcome

    async def _toggle(self, ieee, short, zcl_ep, rid):
        """Manual-only toggle. Attribute reporting keeps ``_states`` live,
        so the common case flips the last reported state in one round-trip;
        read_attr is only the cold-cache fallback. Still deliberately
        non-atomic (arch decision) — which is exactly why the domain layer
        bans toggle in schedules."""
        current = self._states.get(ieee)
        if current is None:
            read = await self._command(
                "read_attr", {"short_addr": short, "endpoint": zcl_ep},
                rid=rid + "-r")
            if read["status"] != "sent_to_zigbee":
                return read
            current = bool(read.get("reply", {}).get("on_off"))
        return await self._command(
            "on_off",
            {"state": "off" if current else "on",
             "short_addr": short, "endpoint": zcl_ep},
            rid=rid)

    def _resolve_targets(self, target_type, target_id):
        """Map an event target to [(ieee, short_addr, zcl_endpoint), ...]."""
        if target_type == "endpoint":
            return [self._resolve_endpoint(target_id)]
        if target_type == "group":
            group = self._repo.get_by_id("groups", target_id)
            if group is None:
                raise ValueError("unknown group: {}".format(target_id))
            members = group.get("member_ids") or []
            if not members:
                raise ValueError("group has no members: {}".format(target_id))
            return [self._resolve_endpoint(m) for m in members]
        raise ValueError("unsupported target_type: {}".format(target_type))

    def _resolve_endpoint(self, endpoint_id):
        entity = self._repo.get_by_id("endpoints", endpoint_id)
        if entity is None:
            raise ValueError("unknown endpoint: {}".format(endpoint_id))
        ieee = entity.get("ieee_address")
        if not ieee:
            raise ValueError(
                "endpoint {} has no ieee_address (pair it first)".format(
                    endpoint_id))
        entry = self._registry.get(ieee)
        if entry is None or not entry.get("short_addr"):
            raise ValueError(
                "device {} not in zigbee registry (never joined)".format(ieee))
        zcl_ep = entity.get("zigbee_endpoint", entry.get("endpoint", 1))
        return ieee, entry["short_addr"], zcl_ep

    def ieee_of(self, endpoint_id):
        """Stable radio identity of an endpoint entity, or None."""
        entity = self._repo.get_by_id("endpoints", endpoint_id)
        return entity.get("ieee_address") if entity else None

    # ── pairing / maintenance ops (exposed via Api) ────────────────────

    async def ping(self):
        # The watchdog's re-probe must reach the wire even while the
        # breaker is open, so bypass the fail-fast check in _command.
        was_down, self._down = self._down, False
        result = await self._command("ping", None)
        if result["status"] != "sent_to_zigbee" and was_down:
            self._down = True
        return result

    async def permit_join(self, duration):
        return await self._command("permit_join", {"duration": duration})

    async def read_state(self, ieee):
        entry = self._registry.get(ieee)
        if entry is None:
            return {"status": "error", "error": "unknown device",
                    "command_id": ""}
        return await self._command(
            "read_attr",
            {"short_addr": entry["short_addr"],
             "endpoint": entry.get("endpoint", 1)})

    def forget_device(self, ieee):
        entry = self._registry.pop(ieee, None)
        self._states.pop(ieee, None)
        self._state_ms.pop(ieee, None)
        self._save_registry()
        if entry is None:
            return {"removed": False}
        self._write_cmd("remove_device",
                        {"ieee_addr": ieee,
                         "short_addr": entry.get("short_addr")})
        return {"removed": True}


def _worst_status(results):
    # error > timeout > success: a partial group failure must stay
    # retryable, and on_off retries are idempotent.
    statuses = [r["status"] for r in results]
    for status in ("error", "timeout"):
        if status in statuses:
            return status
    return "sent_to_zigbee"
