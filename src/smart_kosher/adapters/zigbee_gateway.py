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

from ..ports.device_gateway import (
    EXECUTION_SUCCESS_STATUSES,
    DeviceGateway,
)
from .uart_codec import decode as uart_decode
from .uart_codec import encode as uart_encode

# Acks measured well under 500ms on hardware; 1500ms already means the
# command is lost (coordinator restarts take longer than any retry helps).
_DEFAULT_ACK_TIMEOUT_MS = 1500
_BREAKER_THRESHOLD = 2          # consecutive timeouts before failing fast
_WATCHDOG_UP_MS = 30000         # heartbeat ping interval while link is up
_WATCHDOG_DOWN_MS = 2000        # re-probe interval while link is down

# Enabling reporting is bind + configure_reporting *on the device*, and either
# half can fail after the command itself was accepted -- the outcome only
# arrives later, as an event. Until it succeeds the device is deaf to its own
# wall switch, which is invisible unless we keep asking.
_REPORTING_RETRY_BASE_MS = 30000
_REPORTING_RETRY_MAX_MS = 600000
# Concurrency window, derived from the other end: the coordinator's request
# table is 16 slots (TXN_MAX) and a bind holds one for several seconds. Four
# leaves it comfortably idle for commands while still pipelining. This bounds
# what is *outstanding*, not what is sent per unit time, so a backlog drains as
# fast as the link answers -- ten devices or a thousand.
_REPORTING_WINDOW = 4
# A request the coordinator never answers must not hold its credit forever.
_REPORTING_INFLIGHT_MS = 12000

# Group delivery concurrency. Shares the coordinator's 16-slot request table
# with _REPORTING_WINDOW, so the two together stay well inside it.
_COMMAND_WINDOW = 4

# Ops that address a Zigbee device, and so can be proven delivered. Everything
# else (ping, permit_join) is the coordinator answering about itself.
_DEVICE_OPS = ("on_off", "read_attr", "read_report_cfg")

# The cluster whose reporting the control path depends on.
_CLUSTER_ON_OFF = 0x0006


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
        # ieee -> bool. STRICTLY the device's own word (attribute_report or a
        # read_attr ack). wait_for_report's whole value is that this is never
        # anything we merely believe, so nothing else may write here.
        self._states = {}
        self._state_ms = {}
        # ieee -> bool we last commanded and have no reason to doubt. Kept
        # apart from _states for the reason above; cleared the moment the
        # device actually says something.
        self._expected = {}
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
        # ieee -> {"attempts": int, "due": ticks, "error": str} while the
        # coordinator has not confirmed reporting for the device.
        self._reporting_retry = {}
        # ieee -> credit expiry, for requests sent and not yet answered.
        self._reporting_inflight = {}
        # ieee -> {"active_power": .., "rms_voltage": .., "age_ms": ..} for
        # devices that carry a metering cluster. Passed through as the device
        # sends it -- raw and unscaled; deciding what a number means is a job
        # for whoever displays it.
        self._measurements = {}
        self._measured_ms = {}
        # What the coordinator says it can do, learned from boot/ping. Empty
        # for firmware that predates the advertisement, which is exactly how
        # an old build keeps its old (looser) semantics.
        self._capabilities = ()
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
            if ieee in self._expected:
                # A command we sent outranks a report from before it. Without
                # this the UI flipped back to the old state on the next poll
                # and then to the new one when the report landed -- a visible
                # off / on / off bounce on every tap.
                item["on_off"] = self._expected[ieee]
            if self._suspect.get(ieee):
                item["unreachable"] = True
            # Why reporting is still off, so "its wall switch does nothing"
            # is diagnosable instead of just silent.
            retry = self._reporting_retry.get(ieee)
            if retry and retry.get("error"):
                item["reporting_error"] = retry["error"]
            if ieee in self._measurements:
                item["measurements"] = dict(self._measurements[ieee])
                item["measured_age_ms"] = ticks_diff(
                    ticks_ms(), self._measured_ms[ieee])
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
                # The coordinator reports the *outcome* in payload.status --
                # taking the event's arrival as success marked a failed
                # configure as working, and the device then never reported.
                self._on_reporting_result(
                    payload, payload.get("status", "ok") == "ok")
            elif op == "reporting_failed":
                self._on_reporting_result(payload, False)
            elif op == "device_endpoints":
                self._on_device_endpoints(payload)
            elif op == "device_clusters":
                self._on_device_clusters(payload)
            elif op == "measurement_report":
                self._on_measurement(payload)
            elif op == "device_left":
                self._on_device_left(payload)
            elif op == "network_down":
                self.info["network_up"] = False
            elif op in ("boot", "network_formed"):
                self.info["network_up"] = True
                if payload.get("firmware_version"):
                    self.info["firmware_version"] = payload["firmware_version"]
                if payload.get("target"):
                    self.info["target"] = payload["target"]
                self._learn_capabilities(payload)
        elif mtype == "ack":
            if op == "ping":
                self.info["network_up"] = bool(payload.get("network_up"))
                self.info["firmware_version"] = payload.get("firmware_version")
                self.info["target"] = payload.get("target")
                if payload.get("health"):
                    # Link counters from the coordinator; the only way to tell
                    # a saturated link from a quiet one in the field.
                    self.info["health"] = payload["health"]
                self._learn_capabilities(payload)
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
        # Enqueue rather than send. A single pairing still goes out on the
        # next line, because the sweep serves the queue immediately and one
        # device is well inside the quota -- but a mains outage that brings a
        # whole house back at once cannot turn into one frame per device.
        # Sending here directly was exactly that hole: the rate limit governed
        # retries while first attempts bypassed it.
        state = self._reporting_retry.setdefault(ieee, {})
        state["attempts"] = 0
        state["due"] = ticks_ms()
        self.pump_reporting()

    # ── reporting lifecycle (bind + configure, both fallible) ─────────

    def _request_reporting(self, ieee, entry, attempts):
        """Ask the coordinator to bind + configure reporting, and arm a retry.

        Idempotent and cheap to repeat, so re-requesting is always safe. The
        answer comes back later as reporting_configured / reporting_failed;
        until one of those says ok, the retry deadline stands.
        """
        self._write_cmd("enable_reporting",
                        {"short_addr": entry["short_addr"],
                         "endpoint": entry.get("endpoint", 1)})
        delay = _REPORTING_RETRY_BASE_MS * (1 << min(attempts, 4))
        if delay > _REPORTING_RETRY_MAX_MS:
            delay = _REPORTING_RETRY_MAX_MS
        state = self._reporting_retry.setdefault(ieee, {})
        state["attempts"] = attempts + 1
        state["due"] = ticks_add(ticks_ms(), delay)
        # Spend a credit. It comes back when the coordinator answers, or when
        # this deadline passes with no answer at all.
        self._reporting_inflight[ieee] = ticks_add(ticks_ms(),
                                                   _REPORTING_INFLIGHT_MS)

    def _on_reporting_result(self, payload, ok):
        ieee = self._ieee_for_short(payload.get("short_addr"))
        entry = self._registry.get(ieee) if ieee else None
        if entry is None:
            return

        # ``reporting`` means one specific thing: this device will tell us when
        # its own wall switch is pressed. Only the OnOff cluster answers that.
        # A verdict about a metering cluster used to land here too, so a failed
        # measurement configure flipped a perfectly healthy device to
        # reporting=false and started retrying it -- and once measurements work,
        # a metering success would have masked a genuine OnOff failure.
        # Firmware that predates the cluster field only ever asked about OnOff.
        cluster = payload.get("cluster", _CLUSTER_ON_OFF)
        if cluster != _CLUSTER_ON_OFF:
            if not ok:
                self._log("zigbee measurement reporting failed for", ieee,
                          hex(cluster), payload.get("reason"))
            return

        self._reporting_inflight.pop(ieee, None)   # credit returned
        if ok:
            self._reporting_retry.pop(ieee, None)
            if not entry.get("reporting"):
                entry["reporting"] = True
                self._save_registry()
        else:
            reason = payload.get("reason") or payload.get("status") or "error"
            state = self._reporting_retry.setdefault(ieee, {})
            state.setdefault("attempts", 1)
            state.setdefault("due",
                             ticks_add(ticks_ms(), _REPORTING_RETRY_BASE_MS))
            state["error"] = reason
            if entry.get("reporting"):
                entry["reporting"] = False
                self._save_registry()
            self._log("zigbee reporting failed for", ieee, reason)
        # Self-clocking: an answer frees a credit, so the next device goes out
        # now rather than waiting for a timer that knows nothing about how fast
        # the coordinator is actually replying.
        self.pump_reporting()

    def pump_reporting(self):
        """Send queued enable_reporting requests, up to the credit window.

        Flow control, not rate limiting. The resource being protected is the
        coordinator's in-flight request table -- a *concurrency* limit -- so
        that is what this bounds. An earlier version capped sends per watchdog
        tick instead, which tied throughput to an unrelated heartbeat: with a
        houseful of devices it would have crawled even though each bind
        answers in well under a second, and with a fast link it would have sat
        idle between ticks.

        The queue itself is unbounded, and deliberately so: it is one small
        dict entry per device, so the design does not care whether there are
        ten devices or a thousand. Only ``_REPORTING_WINDOW`` are ever in
        flight, and throughput is whatever the link can actually sustain.

        Safe to call from anywhere -- a join, an answer, or the heartbeat.
        """
        now = ticks_ms()

        # Reclaim credits from requests that were never answered. Without this
        # a coordinator that swallows one request would leak a credit and the
        # window would shrink to nothing.
        for ieee in list(self._reporting_inflight):
            if ticks_diff(self._reporting_inflight[ieee], now) <= 0:
                del self._reporting_inflight[ieee]

        ready = []
        for ieee in list(self._reporting_retry):
            entry = self._registry.get(ieee)
            if entry is None or entry.get("reporting"):
                self._reporting_retry.pop(ieee, None)
                self._reporting_inflight.pop(ieee, None)
                continue
            if ieee in self._reporting_inflight:
                continue
            if ticks_diff(self._reporting_retry[ieee]["due"], now) <= 0:
                ready.append(ieee)

        # Longest-waiting first, so nothing is starved by newer arrivals.
        ready.sort(key=lambda i: ticks_diff(self._reporting_retry[i]["due"], now))
        for ieee in ready:
            if len(self._reporting_inflight) >= _REPORTING_WINDOW:
                break
            # Never give up: a switch that cannot report its own presses is a
            # broken product, and the backoff keeps a dead one cheap.
            self._request_reporting(ieee, self._registry[ieee],
                                    self._reporting_retry[ieee]["attempts"])

    # Cluster ids worth naming. A relay that carries either of these can
    # measure electricity; one that carries neither cannot, whatever the
    # datasheet suggests. Until discovery existed there was no way to tell,
    # because the coordinator only ever spoke OnOff.
    _METERING_CLUSTERS = {0x0702: "metering", 0x0B04: "electrical_measurement"}

    def _on_device_endpoints(self, payload):
        """The device's real endpoint list, discovered after it joined.

        device_joined always reports endpoint 1 because that is all it knows
        at announce time; this is what a two-gang switch needs.
        """
        ieee = self._ieee_for_short(payload.get("short_addr"))
        endpoints = payload.get("endpoints")
        if not ieee or not isinstance(endpoints, list) or not endpoints:
            return
        self._registry[ieee]["endpoints"] = endpoints
        self._save_registry()
        self._log("zigbee endpoints for", ieee, endpoints)

    def _on_device_clusters(self, payload):
        """What one endpoint can do. Recorded so capability questions are
        answered from the device rather than from its model number."""
        ieee = self._ieee_for_short(payload.get("short_addr"))
        clusters = payload.get("in_clusters")
        if not ieee or not isinstance(clusters, list):
            return
        entry = self._registry[ieee]
        found = entry.setdefault("clusters", {})
        found[str(payload.get("endpoint", 1))] = clusters
        measures = sorted(self._METERING_CLUSTERS[c]
                          for c in clusters if c in self._METERING_CLUSTERS)
        if measures:
            entry["measures"] = measures
            # Best effort, and deliberately so: unlike OnOff reporting -- which
            # control correctness depends on and which therefore gets retries --
            # a missing measurement costs a reading, not a schedule. It is
            # requested once here and left alone.
            for cluster in clusters:
                if cluster in self._METERING_CLUSTERS:
                    self._write_cmd("enable_reporting", {
                        "short_addr": entry["short_addr"],
                        "endpoint": payload.get("endpoint", 1),
                        "cluster": cluster})
        self._save_registry()
        self._log("zigbee clusters for", ieee, payload.get("endpoint"),
                  clusters, measures)

    def _on_measurement(self, payload):
        """Live electrical readings from a device that measures.

        Merged rather than replaced: a device reports the electrical and the
        metering cluster separately, and each carries only its own attributes.
        """
        ieee = self._ieee_for_short(payload.get("short_addr"))
        if not ieee or ieee not in self._registry:
            return
        values = self._measurements.setdefault(ieee, {})
        for key, value in payload.items():
            if key in ("short_addr", "endpoint", "cluster"):
                continue
            values[key] = value
        self._measured_ms[ieee] = ticks_ms()

    def _learn_capabilities(self, payload):
        caps = payload.get("capabilities")
        if isinstance(caps, list):
            self._capabilities = tuple(caps)

    def _on_device_left(self, payload):
        """A device announced it is leaving the mesh.

        Without this the registry kept a departed device forever and every
        command to it burned the full ack timeout. ``rejoin`` means it intends
        to come straight back, so only a real departure clears the entry.
        """
        ieee = payload.get("ieee_addr") or \
            self._ieee_for_short(payload.get("short_addr"))
        if not ieee or ieee not in self._registry:
            return
        if payload.get("rejoin"):
            self._suspect[ieee] = True
            return
        self._registry.pop(ieee, None)
        self._states.pop(ieee, None)
        self._state_ms.pop(ieee, None)
        self._expected.pop(ieee, None)
        self._suspect.pop(ieee, None)
        self._reporting_retry.pop(ieee, None)
        self._save_registry()
        self._log("zigbee device left:", ieee)

    def _on_state(self, payload):
        ieee = self._ieee_for_short(payload.get("short_addr"))
        if not ieee or "on_off" not in payload:
            return
        self._expected.pop(ieee, None)   # the device spoke; stop guessing
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
        payload = reply.get("payload") or {}
        status = self._ack_status(op, reply)
        result = {"status": status, "command_id": rid, "reply": payload}
        if status == "error":
            result["error"] = "not_delivered (aps_status={})".format(
                payload.get("aps_status"))
        return result

    def _ack_status(self, op, reply):
        """Map the coordinator's ACK rung onto the port's delivery contract.

        The distinction the port already draws (``accepted_by_h2`` is *not* in
        EXECUTION_SUCCESS_STATUSES, ``confirmed_by_device`` is) only becomes
        real once the coordinator can tell the two apart. So:

        * ``delivered`` -- the device's own radio confirmed the frame. Real
          proof; the Executor may journal the event.
        * anything else from a delivery-capable coordinator -- the command was
          taken but never confirmed. ``accepted_by_h2`` keeps it out of the
          journal, so the Executor retries and, failing that, a schedule stays
          eligible for catch-up instead of being recorded as done.
        * a coordinator without the capability -- unchanged ``sent_to_zigbee``.
          Product B's NanoC6 keeps working on its existing firmware; nothing
          here requires a lockstep flash.

        The ladder applies only to ops aimed at a *device*. ping and
        permit_join are the coordinator answering about itself, with no device
        to confirm anything -- downgrading their perfectly good acks to
        "unproven" made a successful ping look like a failure to ``ping()``,
        which then left the circuit breaker latched open for good. Caught on
        hardware, invisible to every test that did not involve a coordinator
        advertising delivery_ack.
        """
        status = reply.get("status")
        if op not in _DEVICE_OPS:
            return "sent_to_zigbee"
        if status == "delivered":
            return "confirmed_by_device"
        if status == "failed":
            # The coordinator is telling us outright that the command did not
            # reach the device. Read from the ack's own status, never inferred
            # from capabilities: a gateway that has not pinged yet has none,
            # and this used to fall through to sent_to_zigbee -- so a command
            # to an unplugged relay was journaled as executed and never retried.
            # Measured on hardware 2026-08-04 against a powered-off switch.
            return "error"
        if "delivery_ack" in self._capabilities:
            return "accepted_by_h2"
        return "sent_to_zigbee"

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
            if not self._down:
                self.pump_reporting()
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

        results = await self._deliver(targets, action, event_id)
        worst = _worst_status(results)
        outcome = {"status": worst, "command_id": event_id}
        errors = [r.get("error") for r in results if r.get("error")]
        if errors:
            outcome["error"] = "; ".join(errors)
        return outcome

    async def _deliver(self, targets, action, event_id):
        """Deliver to every target, at most ``_COMMAND_WINDOW`` at a time.

        A group used to be delivered strictly one device at a time, each
        waiting out its own round-trip. That is safe but does not scale: at the
        1500 ms ack timeout a fifty-lamp group took over a minute before the
        last lamp came on, which for a Shabbat schedule is a visible failure
        even though every command "worked".

        A window, not a rate — the same reasoning as pump_reporting. The
        resource is the coordinator's request table, so bound what is
        outstanding and let throughput be whatever the radio sustains.
        Deliberately a worker pool rather than fixed batches: one slow device
        must not hold up the three beside it.
        """
        results = [None] * len(targets)
        if len(targets) == 1:
            results[0] = await self._deliver_one(targets[0], action, event_id)
            return results

        # No await between the read and the write, so on a single-threaded
        # loop this hand-off needs no lock.
        cursor = [0]

        async def worker():
            while True:
                index = cursor[0]
                if index >= len(targets):
                    return
                cursor[0] = index + 1
                rid = "{}-{}".format(event_id, index)
                try:
                    results[index] = await self._deliver_one(
                        targets[index], action, rid)
                except Exception as exc:
                    # send() promises never to raise on a delivery problem;
                    # one worker must not break that for the whole group.
                    results[index] = {"status": "error", "error": str(exc),
                                      "command_id": rid}

        # Held in a local until gather returns: on MicroPython a task nobody
        # references is collected before it runs (see panel_mp/bridge.py).
        workers = []
        for _ in range(min(_COMMAND_WINDOW, len(targets))):
            workers.append(asyncio.create_task(worker()))
        await asyncio.gather(*workers)
        return results

    def _expect(self, ieee, action):
        """Believe our own command until the device says otherwise."""
        self._expected[ieee] = (action == "on")

    async def _deliver_one(self, target, action, rid):
        ieee, short, zcl_ep = target
        if action == "toggle":
            result = await self._toggle(ieee, short, zcl_ep, rid)
        else:
            # Set before the round trip, not after: a poll landing while the
            # command is still in flight would otherwise read the pre-command
            # state and undo the UI's optimistic update.
            self._expect(ieee, action)
            result = await self._command(
                "on_off",
                {"state": action, "short_addr": short, "endpoint": zcl_ep},
                rid=rid)
            if result["status"] not in EXECUTION_SUCCESS_STATUSES:
                # It did not get through, so stop claiming it did.
                self._expected.pop(ieee, None)
        if result["status"] == "timeout" and not self._down:
            # Coordinator link looks fine but this device is silent — the
            # classic stale short_addr after an unseen rejoin.
            self._suspect[ieee] = True
        return result

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
            # Against the success set, not one literal: a delivery-capable
            # coordinator answers a read with "delivered", which maps to
            # confirmed_by_device -- comparing to "sent_to_zigbee" alone would
            # call a perfectly good read a failure. (Same shape as the ping
            # bug this pattern already caused once.)
            if read["status"] not in EXECUTION_SUCCESS_STATUSES:
                return read
            current = bool(read.get("reply", {}).get("on_off"))
        action = "off" if current else "on"
        self._expect(ieee, action)
        result = await self._command(
            "on_off",
            {"state": action, "short_addr": short, "endpoint": zcl_ep},
            rid=rid)
        if result["status"] not in EXECUTION_SUCCESS_STATUSES:
            self._expected.pop(ieee, None)
        return result

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
        # Set membership, not one literal. _ack_status keeps ping on
        # sent_to_zigbee today, but a future rung would silently re-latch the
        # breaker here -- which is exactly how this broke the first time.
        if result["status"] not in EXECUTION_SUCCESS_STATUSES and was_down:
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

    async def read_report_config(self, ieee):
        """What reporting interval the device is ACTUALLY running.

        Diagnostic, not part of the control path. It exists because we ask
        every device for min_interval = 0 and one of them reports every ~3
        seconds regardless -- devices clamp to their own minimum, and nothing
        else in the system can tell that from a broken configuration.
        """
        entry = self._registry.get(ieee)
        if entry is None:
            return {"status": "error", "error": "unknown device",
                    "command_id": ""}
        return await self._command(
            "read_report_cfg",
            {"short_addr": entry["short_addr"],
             "endpoint": entry.get("endpoint", 1)})

    def forget_device(self, ieee):
        entry = self._registry.pop(ieee, None)
        self._states.pop(ieee, None)
        self._state_ms.pop(ieee, None)
        self._expected.pop(ieee, None)
        self._save_registry()
        if entry is None:
            return {"removed": False}
        self._write_cmd("remove_device",
                        {"ieee_addr": ieee,
                         "short_addr": entry.get("short_addr")})
        return {"removed": True}


# Weakest-first. A group is only as good as its worst member: a partial
# failure must stay retryable, and on_off retries are idempotent. Note
# accepted_by_h2 ranks below sent_to_zigbee -- it is the rung that means "taken
# but not proven", so a group containing one unproven member must not be
# journaled on the strength of the others.
_STATUS_RANK = ("error", "timeout", "accepted_by_h2", "sent_to_zigbee",
                "confirmed_by_device", "observed_state")


def _worst_status(results):
    statuses = set(r["status"] for r in results)
    for status in _STATUS_RANK:
        if status in statuses:
            return status
    return "sent_to_zigbee"
