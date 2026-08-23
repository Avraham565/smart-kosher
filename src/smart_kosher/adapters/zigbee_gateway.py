"""Production DeviceGateway over the NanoC6/H2 coordinator UART link.

Implements the protocol proven on hardware by firmware/h2_coordinator
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
from ._atomic_io import exists as _exists
from ._atomic_io import flush_file as _flush_file
from ._atomic_io import replace as _replace
from ._atomic_io import sync_filesystem as _sync_filesystem
from .uart_codec import decode as uart_decode
from .uart_codec import encode as uart_encode

# Acks measured well under 500ms on hardware; 1500ms already means the
# command is lost (coordinator restarts take longer than any retry helps).
_DEFAULT_ACK_TIMEOUT_MS = 1500
_BREAKER_THRESHOLD = 2          # consecutive timeouts before failing fast
_WATCHDOG_UP_MS = 30000         # heartbeat ping interval while link is up
_WATCHDOG_DOWN_MS = 2000        # re-probe interval while link is down
# A probe that never reports back must not hold the lock forever. Same
# reasoning as _REPORTING_INFLIGHT_MS: an in-flight marker that only a
# completion path can clear is a latch, not a lock. Comfortably longer
# than the ping it guards (_DEFAULT_ACK_TIMEOUT_MS), so it can never
# expire under a probe that is still legitimately running.
_PROBE_INFLIGHT_MS = 8000

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
        # Set before the load, which writes it: a corrupt registry is reported
        # here rather than mistaken for an empty one, as SettingsStore does.
        self.registry_load_error = None
        # ieee -> {"short_addr": str, "endpoint": int, "reporting": bool}
        self._registry = self._load_registry()
        # ieee -> bool. STRICTLY the device's own word (attribute_report or a
        # read_attr ack). wait_for_report's whole value is that this is never
        # anything we merely believe, so nothing else may write here.
        # (ieee, endpoint) -> bool. One cell per *gang*, not per device: a
        # two-gang switch is one ieee with two relays, and while these shared
        # a cell the later report overwrote the other. That was not only a
        # display fault -- _toggle picks its direction from here, so a toggle
        # on gang 1 after a report from gang 2 sent the opposite command.
        #
        # ``endpoint`` is None for firmware that does not say which gang
        # reported. Lookups go through _state_for, which falls back on the
        # same _endpoint_admits rule the waiters use rather than a second one.
        self._states = {}
        self._state_ms = {}
        # (ieee, endpoint) -> bool we last commanded and have no reason to
        # doubt. Kept apart from _states for the reason above, and keyed the
        # same way for the reason above that: the manual-override rule rests
        # on these two disagreeing, which a shared cell made meaningless.
        self._expected = {}
        # ieee -> [(asyncio.Event, endpoint or None), ...] — state waiters
        self._state_waiters = {}
        # circuit breaker — moved ONLY by ping outcomes: a device that
        # dropped off the mesh times out too, and must not be mistaken
        # for a dead coordinator link.
        self._ping_timeouts = 0
        self._down = False
        # Probe lock expiry, or None when no probe is in flight. A
        # deadline rather than a flag because the only other way out is
        # the probe's own finally, and a task collected before it runs
        # never gets there.
        self._probe_inflight = None
        # ieee -> True when a command to the device timed out while the
        # coordinator link was fine (classic stale-short_addr rejoin);
        # cleared by any report/rejoin from the device.
        self._suspect = {}
        # ieee -> {"attempts": int, "due": ticks, "error": str} while the
        # coordinator has not confirmed reporting for the device.
        self._reporting_retry = {}
        # ieee -> credit expiry, for requests sent and not yet answered.
        self._reporting_inflight = {}
        # What the coordinator says it can do, learned from boot/ping. Empty
        # for firmware that predates the advertisement, which is exactly how
        # an old build keeps its old (looser) semantics.
        self._capabilities = ()
        # coordinator liveness, learned from boot/ping/network_formed
        self.info = {"network_up": None, "firmware_version": None,
                     "target": None}

    # ── registry persistence (hub owns the registry) ──────────────────

    def _load_registry(self):
        """The paired devices, recovered from whichever copy survived.

        This file is the only record that a device belongs to this house. It is
        rewritten on every join, endpoint discovery, cluster discovery and
        reporting change -- so the burst that follows a whole house coming back
        from a power cut is exactly when a write is most likely to be cut in
        half, and losing it un-pairs every relay in the building for good.

        The old version wrote straight onto the live file and answered any
        failure with an empty dict, which is the one answer that cannot be
        distinguished from "no devices yet". Same contract as the repository
        and the settings store now: primary, then .tmp, then .bak.
        """
        if not self._registry_path:
            return {}
        temporary = self._registry_path + ".tmp"
        backup = self._registry_path + ".bak"
        candidates = (self._registry_path, temporary, backup)
        if not any(_exists(path) for path in candidates):
            return {}                       # genuinely nothing paired yet

        errors = []
        for path in candidates:
            try:
                with open(path) as handle:
                    data = json.load(handle)
                if not isinstance(data, dict):
                    raise ValueError("registry must contain a JSON object")
                if path != self._registry_path:
                    _replace(path, self._registry_path)
                    _sync_filesystem()
                    self._log("zigbee registry recovered from", path)
                return data
            except (OSError, ValueError) as exc:
                errors.append(str(exc))

        # Never silently swap a corrupt registry for an empty one: the file is
        # left where it is for inspection, and the failure is said out loud and
        # kept on the instance, in the pattern SettingsStore.load_error set.
        self.registry_load_error = "; ".join(errors)
        self._log("zigbee registry unreadable, keeping the file:",
                  self.registry_load_error)
        return {}

    def _save_registry(self):
        """Write the registry through .tmp, keeping the previous copy as .bak."""
        if not self._registry_path:
            return
        temporary = self._registry_path + ".tmp"
        backup = self._registry_path + ".bak"
        try:
            with open(temporary, "w") as handle:
                json.dump(self._registry, handle)
                _flush_file(handle)
            if _exists(self._registry_path):
                _replace(self._registry_path, backup)
            try:
                _replace(temporary, self._registry_path)
                _sync_filesystem()
            except OSError:
                # Put the backup back rather than leave no primary at all.
                if _exists(backup) and not _exists(self._registry_path):
                    _replace(backup, self._registry_path)
                raise
        except OSError as exc:
            self._log("zigbee registry save failed:", exc)

    # ── public views for status/UI ─────────────────────────────────────

    def _state_for(self, ieee, endpoint):
        """Last reported state of one gang, or None.

        Exact key first, then any report for this device that did not say
        which gang it came from -- old firmware keeps answering for every
        endpoint exactly as it did before, and that fallback is
        _endpoint_admits rather than a rule of its own.
        """
        if (ieee, endpoint) in self._states:
            return self._states[(ieee, endpoint)]
        for key in self._states:
            if key[0] == ieee and _endpoint_admits(endpoint, key[1]):
                return self._states[key]
        return None

    def _expected_for(self, ieee, endpoint):
        """What we last commanded this gang, or None."""
        if (ieee, endpoint) in self._expected:
            return self._expected[(ieee, endpoint)]
        for key in self._expected:
            if key[0] == ieee and _endpoint_admits(endpoint, key[1]):
                return self._expected[key]
        return None

    def _state_age_for(self, ieee, endpoint):
        if (ieee, endpoint) in self._state_ms:
            return self._state_ms[(ieee, endpoint)]
        for key in self._state_ms:
            if key[0] == ieee and _endpoint_admits(endpoint, key[1]):
                return self._state_ms[key]
        return None

    def _forget_device_state(self, ieee):
        """Drop every gang's cell for one device."""
        for store in (self._states, self._state_ms, self._expected):
            for key in list(store):
                if key[0] == ieee:
                    del store[key]

    def devices(self):
        """Registry + last known on/off state, keyed by ieee."""
        out = {}
        for ieee, entry in self._registry.items():
            item = dict(entry)
            primary = entry.get("endpoint", 1)
            # ``on_off`` stays what it always was -- the entry's own endpoint
            # -- so every existing caller keeps reading the same thing. What
            # changes is that gang 2's report can no longer land in it.
            state = self._state_for(ieee, primary)
            if state is not None:
                item["on_off"] = state
                age = self._state_age_for(ieee, primary)
                if age is not None:
                    item["state_age_ms"] = ticks_diff(ticks_ms(), age)
            expected = self._expected_for(ieee, primary)
            if expected is not None:
                # A command we sent outranks a report from before it. Without
                # this the UI flipped back to the old state on the next poll
                # and then to the new one when the report landed -- a visible
                # off / on / off bounce on every tap.
                item["on_off"] = expected
            # Per gang, for callers that address more than the primary one.
            # Additive: nothing that read on_off has to learn about this.
            per_gang = {}
            for endpoint in entry.get("endpoints", [primary]):
                value = self._expected_for(ieee, endpoint)
                if value is None:
                    value = self._state_for(ieee, endpoint)
                if value is not None:
                    per_gang[endpoint] = value
            if per_gang:
                item["endpoint_on_off"] = per_gang
            if self._suspect.get(ieee):
                item["unreachable"] = True
            # Why reporting is still off, so "its wall switch does nothing"
            # is diagnosable instead of just silent.
            for endpoint in self._onoff_endpoints(entry):
                retry = self._reporting_retry.get((ieee, endpoint))
                if retry and retry.get("error"):
                    item["reporting_error"] = retry["error"]
                    break
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
                # ...and a *missing* status is not "ok" either. Defaulting it
                # to success was the same mistake one level down: absence of
                # bad news read as good news.
                self._on_reporting_result(
                    payload, payload.get("status") == "ok")
            elif op == "reporting_failed":
                self._on_reporting_result(payload, False)
            elif op == "device_endpoints":
                self._on_device_endpoints(payload)
            elif op == "device_clusters":
                self._on_device_clusters(payload)
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
        self._arm_reporting(ieee, entry)
        self.pump_reporting()

    # ── reporting lifecycle (bind + configure, both fallible) ─────────

    def _sync_reporting_flag(self, entry):
        """``reporting`` means every OnOff endpoint reports, not just one.

        Kept as a plain bool because devices(), the UI and pump_reporting all
        read it and none of them are in this task. For a single-gang device it
        means exactly what it always did; for a two-gang one it stops claiming
        the device reports when only half of it does -- and the manual-override
        rule does not hold for a gang nobody bound.
        """
        confirmed = entry.get("reporting_endpoints") or []
        entry["reporting"] = all(endpoint in confirmed
                                 for endpoint in self._onoff_endpoints(entry))

    def _onoff_endpoints(self, entry):
        """Every endpoint on this device that speaks OnOff.

        From the device's own cluster discovery, never from its model number.
        Falls back to the entry's single endpoint while discovery is still in
        flight, or against a coordinator too old to report clusters at all --
        which is exactly the behaviour every device had before this.
        """
        clusters = entry.get("clusters") or {}
        found = [endpoint for endpoint in (entry.get("endpoints") or [])
                 if _CLUSTER_ON_OFF in (clusters.get(str(endpoint)) or [])]
        return found or [entry.get("endpoint", 1)]

    def _arm_reporting(self, ieee, entry):
        """Queue a reporting request for each OnOff endpoint not yet confirmed.

        Enqueue rather than send, for the reason _on_device_joined gives: a
        mains outage that brings a whole house back at once must not turn into
        one frame per device per gang.
        """
        confirmed = entry.get("reporting_endpoints") or []
        for endpoint in self._onoff_endpoints(entry):
            if endpoint in confirmed:
                continue
            state = self._reporting_retry.setdefault((ieee, endpoint), {})
            state.setdefault("attempts", 0)
            state.setdefault("due", ticks_ms())

    def _request_reporting(self, ieee, entry, endpoint, attempts):
        """Ask the coordinator to bind + configure reporting, and arm a retry.

        Idempotent and cheap to repeat, so re-requesting is always safe. The
        answer comes back later as reporting_configured / reporting_failed;
        until one of those says ok, the retry deadline stands.
        """
        self._write_cmd("enable_reporting",
                        {"short_addr": entry["short_addr"],
                         "endpoint": endpoint})
        delay = _REPORTING_RETRY_BASE_MS * (1 << min(attempts, 4))
        if delay > _REPORTING_RETRY_MAX_MS:
            delay = _REPORTING_RETRY_MAX_MS
        state = self._reporting_retry.setdefault((ieee, endpoint), {})
        state["attempts"] = attempts + 1
        state["due"] = ticks_add(ticks_ms(), delay)
        # Spend a credit, per endpoint. bind + configure_reporting takes a slot
        # in the coordinator's request table for each one, so a two-gang device
        # really does cost two -- and the window exists to protect that table.
        # Charging it once per device would over-commit exactly the resource
        # the limit is for.
        self._reporting_inflight[(ieee, endpoint)] = ticks_add(
            ticks_ms(), _REPORTING_INFLIGHT_MS)

    def _on_reporting_result(self, payload, ok):
        ieee = self._ieee_for_short(payload.get("short_addr"))
        entry = self._registry.get(ieee) if ieee else None
        if entry is None:
            return

        # ``reporting`` means one specific thing: this device will tell us when
        # its own wall switch is pressed. Only the OnOff cluster answers that.
        #
        # This hub no longer asks for any other cluster -- electrical
        # measurement was removed -- but the guard stays, because a coordinator
        # still running 0.11.x can be mid-flight with a metering configure of
        # its own. Its failure verdict must not knock a healthy device out of
        # reporting, which is exactly what happened before this check existed.
        # Firmware that predates the cluster field only ever asked about OnOff.
        cluster = payload.get("cluster", _CLUSTER_ON_OFF)
        if cluster != _CLUSTER_ON_OFF:
            if not ok:
                self._log("zigbee non-OnOff reporting failed for", ieee,
                          hex(cluster), payload.get("reason"))
            return

        endpoint = payload.get("endpoint", entry.get("endpoint", 1))
        key = (ieee, endpoint)
        self._reporting_inflight.pop(key, None)   # credit returned
        confirmed = entry.setdefault("reporting_endpoints", [])
        if ok:
            self._reporting_retry.pop(key, None)
            if endpoint not in confirmed:
                confirmed.append(endpoint)
                self._sync_reporting_flag(entry)
                self._save_registry()
        else:
            reason = payload.get("reason") or payload.get("status") or "error"
            state = self._reporting_retry.setdefault(key, {})
            state.setdefault("attempts", 1)
            state.setdefault("due",
                             ticks_add(ticks_ms(), _REPORTING_RETRY_BASE_MS))
            state["error"] = reason
            if endpoint in confirmed:
                confirmed.remove(endpoint)
                self._sync_reporting_flag(entry)
                self._save_registry()
            self._log("zigbee reporting failed for", ieee, endpoint, reason)
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
        for key in list(self._reporting_inflight):
            if ticks_diff(self._reporting_inflight[key], now) <= 0:
                del self._reporting_inflight[key]

        ready = []
        for key in list(self._reporting_retry):
            ieee, endpoint = key
            entry = self._registry.get(ieee)
            # Per endpoint, not per device. Keyed by ieee alone, the first gang
            # to confirm cleared the retry for the whole device and the second
            # was never asked again -- the same bug this task exists to fix,
            # one layer up in the bookkeeping.
            if entry is None or endpoint in (entry.get("reporting_endpoints")
                                             or []):
                self._reporting_retry.pop(key, None)
                self._reporting_inflight.pop(key, None)
                continue
            if key in self._reporting_inflight:
                continue
            if ticks_diff(self._reporting_retry[key]["due"], now) <= 0:
                ready.append(key)

        # Longest-waiting first, so nothing is starved by newer arrivals.
        ready.sort(key=lambda k: ticks_diff(self._reporting_retry[k]["due"], now))
        for key in ready:
            if len(self._reporting_inflight) >= _REPORTING_WINDOW:
                break
            # Never give up: a switch that cannot report its own presses is a
            # broken product, and the backoff keeps a dead one cheap.
            self._request_reporting(key[0], self._registry[key[0]], key[1],
                                    self._reporting_retry[key]["attempts"])

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
        """What one endpoint can do, recorded per endpoint.

        Kept after electrical measurement was dropped, because the question it
        answers is not about measuring: a two-gang switch exposes OnOff on both
        endpoint 1 and endpoint 2, and that has to be learned from the device
        rather than assumed from its model number.
        """
        ieee = self._ieee_for_short(payload.get("short_addr"))
        clusters = payload.get("in_clusters")
        if not ieee or not isinstance(clusters, list):
            return
        entry = self._registry[ieee]
        found = entry.setdefault("clusters", {})
        found[str(payload.get("endpoint", 1))] = clusters
        self._save_registry()
        self._log("zigbee clusters for", ieee, payload.get("endpoint"),
                  clusters)
        # This is the moment a second gang becomes known: device_joined only
        # ever says endpoint 1, so until the clusters land there is nothing to
        # tell OnOff on endpoint 2 from a Green Power endpoint that cannot
        # switch anything. Arm whatever just became visible.
        self._arm_reporting(ieee, entry)
        self.pump_reporting()

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
        self._forget_device_state(ieee)
        self._suspect.pop(ieee, None)
        for key in list(self._reporting_retry):
            if key[0] == ieee:
                del self._reporting_retry[key]
        for key in list(self._reporting_inflight):
            if key[0] == ieee:
                del self._reporting_inflight[key]
        self._save_registry()
        self._log("zigbee device left:", ieee)

    def _on_state(self, payload):
        ieee = self._ieee_for_short(payload.get("short_addr"))
        if not ieee or "on_off" not in payload:
            return
        endpoint = payload.get("endpoint")
        # The device spoke -- stop guessing, but only about the gang it spoke
        # for. A report from gang 2 says nothing about what gang 1 is doing.
        for key in list(self._expected):
            if key[0] == ieee and _endpoint_admits(key[1], endpoint):
                del self._expected[key]
        self._states[(ieee, endpoint)] = bool(payload["on_off"])
        self._state_ms[(ieee, endpoint)] = ticks_ms()
        self._suspect.pop(ieee, None)  # it spoke — clearly reachable
        # Waking every waiter for the ieee is what let gang 2's report confirm
        # a command sent to gang 1. A waiter this report cannot answer stays
        # registered, so a later report from its own gang still reaches it.
        still_waiting = []
        for entry in self._state_waiters.pop(ieee, []):
            if _endpoint_admits(entry[1], endpoint):
                entry[0].set()
            else:
                still_waiting.append(entry)
        if still_waiting:
            self._state_waiters[ieee] = still_waiting

    def _ieee_for_short(self, short):
        for ieee, entry in self._registry.items():
            if entry.get("short_addr") == short:
                return ieee
        return None

    # ── observed-state confirmation (ACK level 4) ──────────────────────

    async def wait_for_report(self, ieee, expect, timeout_ms, endpoint=None):
        """Await attribute_report(s) from ``ieee`` until one says
        ``expect`` or the timeout passes. Returns a confirmation dict —
        this is the device's own word, not an ack echo.

        The current state is checked before each wait: the report often
        lands in the same burst as the command's ack, i.e. before the
        caller starts waiting, and must still count.

        ``endpoint`` names which gang the caller is asking about. Without it,
        or against firmware too old to say which gang reported, behaviour is
        exactly what it was — which is what keeps every existing caller
        working. With it, a two-gang device can no longer confirm a command
        to gang 1 because the user happened to press gang 2: that returned
        {"confirmed": True} for a command that was never delivered, and
        observed_state is journalable.
        """
        deadline = ticks_add(ticks_ms(), timeout_ms)
        while True:
            if self._state_for(ieee, endpoint) == expect:
                return {"confirmed": True, "observed": expect}
            remaining = ticks_diff(deadline, ticks_ms())
            if remaining <= 0:
                return {"confirmed": False,
                        "observed": self._state_for(ieee, endpoint)}
            evt = asyncio.Event()
            entry = (evt, endpoint)
            self._state_waiters.setdefault(ieee, []).append(entry)
            try:
                await asyncio.wait_for(evt.wait(), remaining / 1000)
            except asyncio.TimeoutError:
                waiters = self._state_waiters.get(ieee, [])
                if entry in waiters:
                    waiters.remove(entry)
                return {"confirmed": False,
                        "observed": self._state_for(ieee, endpoint)}

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

    async def _command(self, op, payload, rid=None, timeout_ms=None,
                       ignore_breaker=False):
        # ignore_breaker is per request on purpose. The heartbeat has to reach
        # the wire while the breaker is open, but it is the only thing that
        # does, and the way it used to buy itself that -- clearing self._down
        # for the length of its own await -- handed the same exemption to
        # every other caller on the loop.
        if self._down and not ignore_breaker:
            return {"status": "error", "error": "coordinator_down",
                    "command_id": rid or op}
        if rid is None:
            rid = self._next_rid(op)
        evt = asyncio.Event()
        self._pending[rid] = [evt, None]
        try:
            self._write_cmd(op, payload, rid)
        except Exception as exc:
            # The slot is reserved before the write so that an ack arriving
            # inside it has somewhere to land. That ordering is right, but it
            # means a write that throws leaves an entry no other path will
            # ever pop: the ack path needs an ack that is not coming, and the
            # timeout path needs a wait that never started. One slot per
            # failed write, for the life of the process.
            self._pending.pop(rid, None)
            return {"status": "error", "error": str(exc), "command_id": rid}
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
        one probe in flight — a burst of timeouts must not ping-storm.

        The lock carries an expiry for the same reason ``_reporting_inflight``
        does. It is raised *before* the task exists, and the only other way it
        comes down is that task's own ``finally``; a task collected before it
        first runs never reaches one, and this is deliberately fire-and-forget
        (CLAUDE.md names it as one of two such places). A bare flag would then
        stay raised for the life of the process, every later probe would turn
        around at the gate below, and the breaker would lose its evidence
        permanently and silently.
        """
        if self._down:
            return
        if (self._probe_inflight is not None
                and ticks_diff(self._probe_inflight, ticks_ms()) > 0):
            return

        async def probe():
            try:
                await self.ping()
            finally:
                self._probe_inflight = None

        self._probe_inflight = ticks_add(ticks_ms(), _PROBE_INFLIGHT_MS)
        try:
            asyncio.create_task(probe())
        except Exception:
            self._probe_inflight = None

    async def watchdog(self):
        """Heartbeat task: slow pings while the link is up, fast re-probes
        while it is down. The ping's ack (like any inbound frame) clears
        the breaker."""
        while True:
            try:
                await self.ping()
                if not self._down:
                    self.pump_reporting()
            except Exception as exc:
                # The heartbeat must outlive anything it calls. Both branches
                # reach _write_cmd -> self._uart.write, which is a real raiser
                # on a UART fault, and on product A this task is one of seven
                # in a single gather (products/panel/device/main.py): a raise
                # here used to end main() and leave the panel rendering a dead
                # frame. Log and take the next tick.
                self._log("zigbee watchdog error:", exc)
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
            try:
                results[0] = await self._deliver_one(
                    targets[0], action, event_id)
            except Exception as exc:
                # Same promise the worker below keeps, on the path that nearly
                # every command actually takes.
                results[0] = {"status": "error", "error": str(exc),
                              "command_id": event_id}
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
        # references is collected before it runs (see products/panel/device/bridge.py).
        workers = []
        for _ in range(min(_COMMAND_WINDOW, len(targets))):
            workers.append(asyncio.create_task(worker()))
        await asyncio.gather(*workers)
        return results

    def _expect(self, ieee, endpoint, action):
        """Believe our own command until that gang says otherwise."""
        self._expected[(ieee, endpoint)] = (action == "on")

    async def _deliver_one(self, target, action, rid):
        ieee, short, zcl_ep = target
        if action == "toggle":
            result = await self._toggle(ieee, short, zcl_ep, rid)
        else:
            # Set before the round trip, not after: a poll landing while the
            # command is still in flight would otherwise read the pre-command
            # state and undo the UI's optimistic update.
            self._expect(ieee, zcl_ep, action)
            result = await self._command(
                "on_off",
                {"state": action, "short_addr": short, "endpoint": zcl_ep},
                rid=rid)
            if result["status"] not in EXECUTION_SUCCESS_STATUSES:
                # It did not get through, so stop claiming it did.
                self._expected.pop((ieee, zcl_ep), None)
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
        current = self._state_for(ieee, zcl_ep)
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
            reply = read.get("reply") or {}
            if "on_off" not in reply:
                # Treated exactly like the failed read above, because that is
                # what it is: the round trip worked and told us nothing. It
                # used to fall to bool(None) -> False -> "the lamp is off" ->
                # toggle turns it on, every time, whatever it was doing.
                return {"status": "error",
                        "error": "read_attr reply carried no on_off",
                        "command_id": read.get("command_id", rid)}
            current = bool(reply["on_off"])
        action = "off" if current else "on"
        self._expect(ieee, zcl_ep, action)
        result = await self._command(
            "on_off",
            {"state": action, "short_addr": short, "endpoint": zcl_ep},
            rid=rid)
        if result["status"] not in EXECUTION_SUCCESS_STATUSES:
            self._expected.pop((ieee, zcl_ep), None)
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

    def confirm_target(self, endpoint_id):
        """``(ieee, zcl_endpoint)`` a command to this entity would address.

        Answered here rather than worked out by the caller because the caller
        cannot: resolving the endpoint means letting the entity's
        zigbee_endpoint override the registry's, and that needs the registry
        entry, which only this class holds. A second copy of that rule
        somewhere else is a copy that drifts, and this one decides which gang
        a confirmation waits on.

        Same resolution the command takes, deliberately. If the command went to
        endpoint 3 and only endpoint 1 ever reports, the confirmation must fail
        -- nothing answered from where we commanded, so nothing was delivered,
        and "unconfirmed" is the honest answer. Falling back to the registry's
        endpoint would confirm on a report from a gang we never addressed,
        which is the false positive this whole line of work exists to remove.

        None when the entity is unknown, unpaired, or never joined -- the cases
        where the command itself would not have gone out either.
        """
        try:
            ieee, _short, zcl_ep = self._resolve_endpoint(endpoint_id)
        except ValueError:
            return None
        return ieee, zcl_ep

    # ── pairing / maintenance ops (exposed via Api) ────────────────────

    async def ping(self):
        """The heartbeat, and the only command that outranks the breaker.

        It has to reach the wire while the link is down -- that is how the
        link is ever found to be up again. It used to buy that by setting
        self._down to False across its own await and putting it back
        afterwards, which disarmed the fail-fast for everything else for as
        long as the ping ran: while down, the watchdog is inside that await
        for 1500 of every 3500 ms, and a group send landing in the window
        reached the wire, timed out per member, and had every one of its
        devices marked unreachable by _deliver_one.

        Nothing has to put the breaker back now, because nothing takes it
        down. A ping that is answered clears it in process_line like any other
        inbound frame, and a ping that times out is counted by _command.
        """
        return await self._command("ping", None, ignore_breaker=True)

    async def permit_join(self, duration):
        return await self._command("permit_join", {"duration": duration})

    async def read_state(self, ieee, endpoint=None):
        """Ask one gang what state it is in.

        ``endpoint`` defaults to the registry's own, which is what every
        caller got before and is right for a single-gang device. Without the
        parameter there was no way to read gang 2 at all -- and a caller that
        flips a relay to identify it has to be able to put it back.
        """
        entry = self._registry.get(ieee)
        if entry is None:
            return {"status": "error", "error": "unknown device",
                    "command_id": ""}
        if endpoint is None:
            endpoint = entry.get("endpoint", 1)
        return await self._command(
            "read_attr",
            {"short_addr": entry["short_addr"], "endpoint": endpoint})

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
        self._forget_device_state(ieee)
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


def _endpoint_admits(want, seen):
    """Whether a report from endpoint ``seen`` may answer a waiter that asked
    about endpoint ``want``.

    Unknown on either side falls back to the pre-endpoint behaviour: a caller
    that does not name a gang, and firmware that does not say which gang
    reported, both keep answering exactly as they did before. Only when both
    are known can the two disagree, and only then is anything refused.
    """
    return want is None or seen is None or want == seen


def _worst_status(results):
    statuses = set(r["status"] for r in results)
    for status in _STATUS_RANK:
        if status in statuses:
            return status
    return "sent_to_zigbee"
