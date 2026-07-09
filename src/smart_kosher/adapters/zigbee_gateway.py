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

Threading model: the hub runs one cooperative asyncio loop. ``poll()``
drains spontaneous events and is called from a periodic task; ``send()``
writes a command and reads inline until its ack (processing any events it
meets on the way). The two never run concurrently, so no locking is
needed — but send() does block the loop for up to its timeout, which is
acceptable at pilot scale (acks measured well under a second on hardware).

The UART object is duck-typed (``read(n)``/``write(bytes)``): the device
passes ``machine.UART``, tests pass a fake.
"""

try:
    import ujson as json
except ImportError:
    import json

try:
    from time import sleep_ms, ticks_add, ticks_diff, ticks_ms
except ImportError:  # CPython
    import time as _time

    def ticks_ms():
        return int(_time.monotonic() * 1000)

    def ticks_add(t, delta):
        return t + delta

    def ticks_diff(a, b):
        return a - b

    def sleep_ms(ms):
        _time.sleep(ms / 1000.0)

from ..ports.device_gateway import DeviceGateway
from .uart_codec import decode as uart_decode
from .uart_codec import encode as uart_encode

_MAX_LINE = 512          # coordinator firmware MAX_LINE
_READ_CHUNK = 256        # explicit size: uart.read() without one can block
_DEFAULT_ACK_TIMEOUT_MS = 5000
_POLL_SLEEP_MS = 20


class ZigbeeGateway(DeviceGateway):
    def __init__(self, uart, repository, registry_path=None,
                 ack_timeout_ms=_DEFAULT_ACK_TIMEOUT_MS, log=print):
        self._uart = uart
        self._repo = repository
        self._registry_path = registry_path
        self._ack_timeout_ms = ack_timeout_ms
        self._log = log
        self._buf = b""
        self._seq = 0
        # ieee -> {"short_addr": str, "endpoint": int, "reporting": bool}
        self._registry = self._load_registry()
        # ieee -> True/False, from attribute_report and read_attr acks
        self._states = {}
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
            out[ieee] = item
        return out

    def status_info(self):
        info = {"gateway": "zigbee", "devices": len(self._registry)}
        info.update(self.info)
        return info

    # ── inbound: events and stray acks ─────────────────────────────────

    def poll(self):
        """Drain waiting UART lines; returns how many messages were handled.

        Call periodically from the shared asyncio loop so spontaneous
        events (device_joined, attribute_report) are consumed even when no
        command is in flight.
        """
        handled = 0
        for msg in self._read_lines():
            self._handle_async(msg)
            handled += 1
        return handled

    def _read_lines(self):
        chunk = self._uart.read(_READ_CHUNK)
        while chunk:
            self._buf += chunk
            chunk = self._uart.read(_READ_CHUNK)
        while b"\n" in self._buf:
            line, self._buf = self._buf.split(b"\n", 1)
            line = line.strip()
            if not line:
                continue
            try:
                yield uart_decode(line)
            except ValueError:
                # console noise / corrupt frame — protocol says skip
                continue
        if len(self._buf) > _MAX_LINE * 4:
            # a newline-free flood (e.g. wrong baud) — don't eat the heap
            self._buf = b""

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
        self._save_registry()
        self._log("zigbee device", "joined:" if first_join else "rejoined:",
                  ieee, short)
        # Rejoin invalidates the device's binding-independent config only
        # rarely, but reporting is cheap to (re)request and idempotent.
        self._request_reporting(short, entry["endpoint"])

    def _request_reporting(self, short, endpoint):
        # Fire and forget: the reporting_configured event flips the flag.
        self._write_cmd("enable_reporting",
                        {"short_addr": short, "endpoint": endpoint})

    def _on_state(self, payload):
        ieee = self._ieee_for_short(payload.get("short_addr"))
        if ieee and "on_off" in payload:
            self._states[ieee] = bool(payload["on_off"])

    def _ieee_for_short(self, short):
        for ieee, entry in self._registry.items():
            if entry.get("short_addr") == short:
                return ieee
        return None

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

    def _await_ack(self, rid, op, timeout_ms=None):
        """Read until the ack/error for ``rid`` arrives; events met on the
        way are handled normally so a rejoin during a command still heals
        the registry."""
        if timeout_ms is None:
            timeout_ms = self._ack_timeout_ms
        deadline = ticks_add(ticks_ms(), timeout_ms)
        while ticks_diff(deadline, ticks_ms()) > 0:
            for msg in self._read_lines():
                self._handle_async(msg)
                if msg.get("request_id") != rid:
                    continue
                if msg.get("type") == "ack" and msg.get("op") == op:
                    return msg
                if msg.get("type") == "error":
                    return msg
            sleep_ms(_POLL_SLEEP_MS)
        return None

    def _command(self, op, payload, rid=None, timeout_ms=None):
        rid = self._write_cmd(op, payload, rid)
        reply = self._await_ack(rid, op, timeout_ms)
        if reply is None:
            return {"status": "timeout", "command_id": rid}
        if reply.get("type") == "error":
            code = (reply.get("payload") or {}).get("code", "coordinator_error")
            return {"status": "error", "error": code, "command_id": rid}
        result = {"status": "sent_to_zigbee", "command_id": rid}
        result["reply"] = reply.get("payload") or {}
        return result

    # ── DeviceGateway contract ─────────────────────────────────────────

    def send(self, event):
        """Deliver one planner/manual event. Never raises on delivery
        problems — returns a retryable status instead (Executor decides)."""
        target_type = event.get("target_type")
        target_id = event.get("target_id")
        action = event.get("action_type")
        event_id = event.get("event_id", "")

        try:
            endpoints = self._resolve_targets(target_type, target_id)
        except ValueError as exc:
            return {"status": "error", "error": str(exc),
                    "command_id": event_id}

        results = []
        for n, (short, zcl_ep) in enumerate(endpoints):
            rid = "{}-{}".format(event_id, n) if len(endpoints) > 1 else event_id
            if action == "toggle":
                results.append(self._toggle(short, zcl_ep, rid))
            else:
                results.append(self._command(
                    "on_off",
                    {"state": action, "short_addr": short, "endpoint": zcl_ep},
                    rid=rid))

        worst = _worst_status(results)
        outcome = {"status": worst, "command_id": event_id}
        errors = [r.get("error") for r in results if r.get("error")]
        if errors:
            outcome["error"] = "; ".join(errors)
        return outcome

    def _toggle(self, short, zcl_ep, rid):
        """Manual-only toggle = read current state, send the opposite.

        Two round-trips, deliberately non-atomic (arch decision) — which
        is exactly why the domain layer already bans toggle in schedules.
        """
        read = self._command(
            "read_attr", {"short_addr": short, "endpoint": zcl_ep},
            rid=rid + "-r")
        if read["status"] != "sent_to_zigbee":
            return read
        current = bool(read.get("reply", {}).get("on_off"))
        return self._command(
            "on_off",
            {"state": "off" if current else "on",
             "short_addr": short, "endpoint": zcl_ep},
            rid=rid)

    def _resolve_targets(self, target_type, target_id):
        """Map an event target to [(short_addr, zcl_endpoint), ...]."""
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
        return entry["short_addr"], zcl_ep

    # ── pairing / maintenance ops (exposed via Api) ────────────────────

    def ping(self):
        return self._command("ping", None)

    def permit_join(self, duration):
        return self._command("permit_join", {"duration": duration})

    def read_state(self, ieee):
        entry = self._registry.get(ieee)
        if entry is None:
            return {"status": "error", "error": "unknown device",
                    "command_id": ""}
        result = self._command(
            "read_attr",
            {"short_addr": entry["short_addr"],
             "endpoint": entry.get("endpoint", 1)})
        return result

    def forget_device(self, ieee):
        entry = self._registry.pop(ieee, None)
        self._states.pop(ieee, None)
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
