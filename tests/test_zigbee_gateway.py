"""ZigbeeGateway adapter tests — against the hardware-proven coordinator
protocol (experiments/zigbee_probe, Gate 2+3 pass on H2 and NanoC6).

FakeUart plays the coordinator: frames are real CRC32+JSON lines through
the same uart_codec the device uses, so a drift between the adapter and
the proven envelope fails here first. Replies are delivered synchronously
into ``gateway.process_line`` — exactly what the device's reader task does,
minus the wire.
"""

import asyncio
import os
import tempfile
import unittest

from smart_kosher.adapters import MemoryRepository, uart_decode, uart_encode
from smart_kosher.adapters.memory_repository import MemoryEventJournal
from smart_kosher.adapters.zigbee_gateway import ZigbeeGateway, ticks_ms
from smart_kosher.application.control_service import ControlService
from smart_kosher.application.executor import Executor

IEEE = "a4:c1:38:6b:47:9d:c2:55"
SHORT = "0xa7d8"

run = asyncio.run


def joined_event(ieee=IEEE, short=SHORT, endpoint=1):
    return {"version": 1, "type": "event", "op": "device_joined",
            "payload": {"ieee_addr": ieee, "short_addr": short,
                        "endpoint": endpoint}}


def report_event(on_off, short=SHORT):
    return {"version": 1, "type": "event", "op": "attribute_report",
            "payload": {"on_off": on_off, "short_addr": short,
                        "endpoint": 1}}


def ack_for(msg, payload=None, status="ok"):
    return {"version": 1, "type": "ack", "op": msg["op"],
            "request_id": msg["request_id"], "status": status,
            "payload": payload if payload is not None else msg.get("payload", {})}


class FakeUart:
    """Coordinator stand-in: written commands are decoded and answered by
    the ``autoresponder`` (msg -> list of reply dicts, or None), delivered
    straight into the gateway like the device reader task would."""

    def __init__(self):
        self.written = []
        self.deliver = None  # set to gateway.process_line by the test
        self.autoresponder = None

    def write(self, data):
        msg = uart_decode(data)
        self.written.append(msg)
        if self.autoresponder is not None:
            for reply in (self.autoresponder(msg) or []):
                self.feed(reply)

    def feed(self, msg):
        line = msg if isinstance(msg, bytes) else uart_encode(msg)
        return self.deliver(line)


def make_event(action="on", target_type="endpoint", target_id="ep1",
               event_id="ev1"):
    return {
        "event_id": event_id,
        "schedule_id": "manual",
        "source_date": (2026, 7, 9),
        "utc_minute": 0,
        "target_type": target_type,
        "target_id": target_id,
        "action_type": action,
        "action_data": {},
    }


class GatewayTestCase(unittest.TestCase):
    def setUp(self):
        self.uart = FakeUart()
        self.repo = MemoryRepository()
        self.repo.upsert("endpoints", {
            "id": "ep1", "name": "boiler", "ieee_address": IEEE})
        self.gateway = ZigbeeGateway(
            self.uart, self.repo, ack_timeout_ms=80, log=lambda *a: None)
        self.uart.deliver = self.gateway.process_line

    def join_device(self, **kwargs):
        self.uart.feed(joined_event(**kwargs))

    def written_ops(self):
        return [m["op"] for m in self.uart.written]


class SendTests(GatewayTestCase):
    def test_on_sends_proven_frame_and_returns_sent_to_zigbee(self):
        self.join_device()
        self.uart.autoresponder = lambda m: [ack_for(m)]

        result = run(self.gateway.send(make_event("on")))

        self.assertEqual("sent_to_zigbee", result["status"])
        self.assertEqual("ev1", result["command_id"])
        cmd = [m for m in self.uart.written if m["op"] == "on_off"][-1]
        self.assertEqual("command", cmd["type"])
        self.assertEqual(1, cmd["version"])
        self.assertEqual("ev1", cmd["request_id"])
        self.assertEqual(
            {"state": "on", "short_addr": SHORT, "endpoint": 1},
            cmd["payload"])

    def test_no_ack_returns_retryable_timeout(self):
        self.join_device()
        result = run(self.gateway.send(make_event("off")))
        self.assertEqual("timeout", result["status"])

    def test_coordinator_error_maps_to_error_status(self):
        self.join_device()
        self.uart.autoresponder = lambda m: [{
            "version": 1, "type": "error", "request_id": m["request_id"],
            "payload": {"code": "unknown_device"}}]
        result = run(self.gateway.send(make_event("on")))
        self.assertEqual("error", result["status"])
        self.assertIn("unknown_device", result["error"])

    def test_unpaired_endpoint_is_error_without_uart_write(self):
        self.repo.upsert("endpoints", {"id": "ep2", "name": "no-radio"})
        result = run(self.gateway.send(make_event("on", target_id="ep2")))
        self.assertEqual("error", result["status"])
        self.assertNotIn("on_off", self.written_ops())

    def test_known_ieee_but_never_joined_is_error(self):
        result = run(self.gateway.send(make_event("on")))
        self.assertEqual("error", result["status"])
        self.assertIn("registry", result["error"])

    def test_zigbee_endpoint_on_entity_overrides_registry(self):
        self.join_device(endpoint=1)
        self.repo.upsert("endpoints", {
            "id": "ep1", "name": "boiler", "ieee_address": IEEE,
            "zigbee_endpoint": 3})
        self.uart.autoresponder = lambda m: [ack_for(m)]
        run(self.gateway.send(make_event("on")))
        cmd = [m for m in self.uart.written if m["op"] == "on_off"][-1]
        self.assertEqual(3, cmd["payload"]["endpoint"])


class BreakerTests(GatewayTestCase):
    def _open_breaker(self):
        run(self.gateway.ping())   # ping timeout 1
        run(self.gateway.ping())   # ping timeout 2 -> down
        self.assertTrue(self.gateway.status_info()["link_down"])

    def test_ping_timeouts_open_breaker_and_commands_fail_fast(self):
        self.join_device()
        self._open_breaker()

        writes_before = len(self.uart.written)
        result = run(self.gateway.send(make_event("on")))
        self.assertEqual("error", result["status"])
        self.assertIn("coordinator_down", result["error"])
        self.assertEqual(writes_before, len(self.uart.written))  # no wait, no wire

    def test_device_timeout_marks_suspect_but_not_link_down(self):
        self.join_device()

        async def scenario():
            # the device never acks, but the probe ping IS answered —
            # the link is fine, the device is the problem
            self.uart.autoresponder = lambda m: (
                [ack_for(m, {"network_up": True})] if m["op"] == "ping"
                else None)
            result = await self.gateway.send(make_event("on"))
            await asyncio.sleep(0.05)  # let the probe task finish
            return result

        result = run(scenario())
        self.assertEqual("timeout", result["status"])
        self.assertFalse(self.gateway.status_info()["link_down"])
        self.assertTrue(self.gateway.devices()[IEEE].get("unreachable"))
        self.assertIn("ping", self.written_ops())  # the probe went out

    def test_rejoin_clears_unreachable(self):
        self.join_device()
        run(self.gateway.send(make_event("on")))   # timeout -> suspect
        self.assertTrue(self.gateway.devices()[IEEE].get("unreachable"))
        self.join_device(short="0xbeef")           # device came back
        self.assertFalse(self.gateway.devices()[IEEE].get("unreachable"))

    def test_any_inbound_frame_closes_breaker(self):
        self.join_device()
        self._open_breaker()

        self.uart.feed(report_event(True))  # link is alive after all
        self.assertFalse(self.gateway.status_info()["link_down"])
        self.uart.autoresponder = lambda m: [ack_for(m)]
        result = run(self.gateway.send(make_event("on")))
        self.assertEqual("sent_to_zigbee", result["status"])

    def test_ping_probes_the_wire_even_while_down(self):
        self.join_device()
        self._open_breaker()

        self.uart.autoresponder = lambda m: [ack_for(m, {"network_up": True})]
        result = run(self.gateway.ping())
        self.assertEqual("sent_to_zigbee", result["status"])
        self.assertFalse(self.gateway.status_info()["link_down"])


class ToggleTests(GatewayTestCase):
    def test_toggle_uses_live_reported_state_in_one_round_trip(self):
        self.join_device()
        self.uart.feed(report_event(True))  # reporting keeps the cache warm
        self.uart.autoresponder = lambda m: [ack_for(m)]

        result = run(self.gateway.send(make_event("toggle")))

        self.assertEqual("sent_to_zigbee", result["status"])
        self.assertNotIn("read_attr", self.written_ops())
        cmd = [m for m in self.uart.written if m["op"] == "on_off"][-1]
        self.assertEqual("off", cmd["payload"]["state"])

    def test_toggle_cold_cache_falls_back_to_read_then_flips(self):
        self.join_device()

        def responder(m):
            if m["op"] == "read_attr":
                return [ack_for(m, {"on_off": False, "short_addr": SHORT})]
            return [ack_for(m)]
        self.uart.autoresponder = responder

        result = run(self.gateway.send(make_event("toggle")))

        self.assertEqual("sent_to_zigbee", result["status"])
        ops = [op for op in self.written_ops() if op != "enable_reporting"]
        self.assertEqual(["read_attr", "on_off"], ops)
        cmd = [m for m in self.uart.written if m["op"] == "on_off"][-1]
        self.assertEqual("on", cmd["payload"]["state"])

    def test_toggle_read_failure_aborts_without_on_off(self):
        self.join_device()
        result = run(self.gateway.send(make_event("toggle")))
        self.assertEqual("timeout", result["status"])
        self.assertNotIn("on_off", self.written_ops())


class GroupTests(GatewayTestCase):
    def setUp(self):
        super().setUp()
        self.repo.upsert("endpoints", {
            "id": "ep2", "name": "urn",
            "ieee_address": "aa:bb:cc:dd:ee:ff:00:11"})
        self.repo.upsert("groups", {
            "id": "g1", "name": "kitchen", "member_ids": ["ep1", "ep2"]})
        self.join_device()
        self.join_device(ieee="aa:bb:cc:dd:ee:ff:00:11", short="0x1111")

    def test_group_sends_one_command_per_member(self):
        self.uart.autoresponder = lambda m: [ack_for(m)]
        result = run(self.gateway.send(
            make_event("on", target_type="group", target_id="g1")))
        self.assertEqual("sent_to_zigbee", result["status"])
        cmds = [m for m in self.uart.written if m["op"] == "on_off"]
        self.assertEqual({SHORT, "0x1111"},
                         {m["payload"]["short_addr"] for m in cmds})
        # per-member request ids stay unique but derive from the event
        self.assertEqual({"ev1-0", "ev1-1"},
                         {m["request_id"] for m in cmds})

    def test_partial_group_failure_stays_retryable(self):
        def responder(m):
            if m["op"] != "on_off":
                return [ack_for(m)]
            if m["payload"]["short_addr"] == SHORT:
                return [ack_for(m)]
            return None  # second member never acks
        self.uart.autoresponder = responder
        result = run(self.gateway.send(
            make_event("on", target_type="group", target_id="g1")))
        self.assertEqual("timeout", result["status"])


class LargeGroupTests(GatewayTestCase):
    """A group big enough that delivering it one device at a time matters."""

    SIZE = 12

    def setUp(self):
        super().setUp()
        members = []
        for n in range(self.SIZE):
            ieee, short = "aa:bb:cc:dd:ee:ff:01:%02x" % n, "0x30%02x" % n
            self.repo.upsert("endpoints", {"id": "big%d" % n,
                                           "name": "lamp %d" % n,
                                           "ieee_address": ieee})
            self.join_device(ieee=ieee, short=short)
            members.append("big%d" % n)
        self.repo.upsert("groups", {"id": "big", "name": "all lamps",
                                    "member_ids": members})

    def _event(self):
        return make_event("on", target_type="group", target_id="big")

    def test_delivery_is_bounded_by_the_window_not_the_group_size(self):
        # Nothing answers, so every command sits in flight -- which is exactly
        # what makes the number outstanding observable.
        self.uart.autoresponder = None

        async def scenario():
            task = asyncio.create_task(self.gateway.send(self._event()))
            for _ in range(8):        # let every startable worker write
                await asyncio.sleep(0)
            inflight = self.written_ops().count("on_off")
            await task
            return inflight

        self.assertEqual(4, run(scenario()),
                         "the whole group went out at once")

    def test_every_member_is_still_delivered(self):
        self.uart.autoresponder = lambda m: [ack_for(m)]
        result = run(self.gateway.send(self._event()))
        cmds = [m for m in self.uart.written if m["op"] == "on_off"]
        self.assertEqual(self.SIZE, len(cmds))
        self.assertEqual(self.SIZE, len({m["request_id"] for m in cmds}),
                         "concurrent members need distinct request ids")
        self.assertEqual("sent_to_zigbee", result["status"])

    def test_one_silent_member_does_not_hold_up_the_rest(self):
        # A worker pool, not fixed batches: the slow device must not stall the
        # three beside it.
        silent = "0x3005"

        def responder(m):
            if m["op"] == "on_off" and m["payload"]["short_addr"] == silent:
                return None
            return [ack_for(m)]

        self.uart.autoresponder = responder
        result = run(self.gateway.send(self._event()))
        acked = [m for m in self.uart.written if m["op"] == "on_off"]
        self.assertEqual(self.SIZE, len(acked), "some members never went out")
        self.assertEqual("timeout", result["status"])


class RegistryTests(GatewayTestCase):
    def test_join_registers_device_and_requests_reporting(self):
        self.join_device()
        self.assertIn(IEEE, self.gateway.devices())
        self.assertEqual(SHORT, self.gateway.devices()[IEEE]["short_addr"])
        reporting = [m for m in self.uart.written
                     if m["op"] == "enable_reporting"]
        self.assertEqual(1, len(reporting))
        self.assertEqual(SHORT, reporting[0]["payload"]["short_addr"])

    def test_rejoin_heals_short_addr_for_next_send(self):
        self.join_device()
        self.join_device(short="0xbeef")  # rejoin with a new address
        self.uart.autoresponder = lambda m: [ack_for(m)]
        run(self.gateway.send(make_event("on")))
        cmd = [m for m in self.uart.written if m["op"] == "on_off"][-1]
        self.assertEqual("0xbeef", cmd["payload"]["short_addr"])

    def test_reporting_configured_flips_flag(self):
        self.join_device()
        self.assertFalse(self.gateway.devices()[IEEE]["reporting"])
        self.uart.feed({"version": 1, "type": "event",
                        "op": "reporting_configured",
                        "payload": {"status": "ok", "short_addr": SHORT,
                                    "endpoint": 1}})
        self.assertTrue(self.gateway.devices()[IEEE]["reporting"])

    def _reporting_result(self, op, **payload):
        payload.setdefault("short_addr", SHORT)
        payload.setdefault("endpoint", 1)
        self.uart.feed({"version": 1, "type": "event", "op": op,
                        "payload": payload})

    def test_failed_configure_does_not_claim_reporting_works(self):
        # The event's arrival is not the outcome -- payload.status is. Taking
        # arrival as success left a device deaf to its own wall switch while
        # the registry insisted reporting was on.
        self.join_device()
        self._reporting_result("reporting_configured", status="error")
        device = self.gateway.devices()[IEEE]
        self.assertFalse(device["reporting"])
        self.assertEqual("error", device["reporting_error"])

    def test_a_metering_failure_does_not_disown_a_healthy_switch(self):
        # This was happening live: the metering configure fails on every
        # device, and because the verdict carried no cluster the hub flipped a
        # perfectly good OnOff device to reporting=false and started retrying.
        # This hub no longer asks for metering at all, but a coordinator still
        # running 0.11.x can be mid-flight with one -- so the guard stays.
        self.join_device()
        self._reporting_result("reporting_configured", status="ok",
                               cluster=0x0006)
        self.assertTrue(self.gateway.devices()[IEEE]["reporting"])

        self._reporting_result("reporting_failed", cluster=0x0B04,
                               reason="configure_send_failed")
        device = self.gateway.devices()[IEEE]
        self.assertTrue(device["reporting"], "OnOff reporting was disowned")
        self.assertNotIn("reporting_error", device)
        self.assertNotIn(IEEE, self.gateway._reporting_retry)

    def test_a_metering_success_cannot_vouch_for_the_switch(self):
        # The mirror image: a metering success from an older coordinator must
        # not be read as proof that wall-switch reporting is fine.
        self.join_device()
        self._reporting_result("reporting_failed", cluster=0x0006,
                               reason="bind_failed")
        self.assertFalse(self.gateway.devices()[IEEE]["reporting"])

        self._reporting_result("reporting_configured", status="ok",
                               cluster=0x0702)
        self.assertFalse(self.gateway.devices()[IEEE]["reporting"],
                         "a metering result vouched for OnOff")
        self.assertIn(IEEE, self.gateway._reporting_retry,
                      "the OnOff retry must survive")

    def test_firmware_without_a_cluster_field_is_treated_as_on_off(self):
        # Older builds only ever configured OnOff, so an absent field means it.
        self.join_device()
        self._reporting_result("reporting_configured", status="ok")
        self.assertTrue(self.gateway.devices()[IEEE]["reporting"])

    def test_reporting_failed_event_is_recorded(self):
        self.join_device()
        self._reporting_result("reporting_failed", reason="bind_failed")
        device = self.gateway.devices()[IEEE]
        self.assertFalse(device["reporting"])
        self.assertEqual("bind_failed", device["reporting_error"])

    def test_failed_reporting_is_retried_by_the_watchdog(self):
        self.join_device()
        self._reporting_result("reporting_failed", reason="bind_failed")
        before = self._sent()

        # Not yet due -- the backoff must not turn into a request storm.
        self.gateway.pump_reporting()
        self.assertEqual(before, self._sent())

        self.gateway._reporting_retry[IEEE]["due"] = ticks_ms() - 1
        self.gateway.pump_reporting()
        self.assertEqual(before + 1, self._sent())

    @staticmethod
    def _addr(n):
        return "11:22:33:44:55:66:77:%02x" % n, "0x10%02x" % n

    def _backlog(self, count):
        """``count`` devices queued for reporting and all eligible now."""
        for n in range(count):
            ieee, short = self._addr(n)
            self.join_device(ieee=ieee, short=short)
        for n in range(count):
            ieee, _ = self._addr(n)
            self.gateway._reporting_retry[ieee]["due"] = ticks_ms() - (n + 1)
        # The joins above already spent the window; treat those attempts as
        # settled so each test measures its own sends.
        self.gateway._reporting_inflight.clear()
        return self._sent()

    def _sent(self):
        return self.written_ops().count("enable_reporting")

    def test_a_single_pairing_is_still_served_immediately(self):
        # Routing joins through the queue must not make "add device" feel slow.
        self.join_device()
        self.assertIn("enable_reporting", self.written_ops())

    def test_only_the_window_is_ever_in_flight(self):
        # The resource being protected is the coordinator's request table, so
        # what must be bounded is how many are *outstanding* -- not how many
        # are sent per unit time. A mass rejoin after a power cut is the case
        # that matters, and first attempts used to bypass the bound entirely.
        base = self._backlog(50)
        self.gateway.pump_reporting()
        self.assertEqual(4, self._sent() - base,
                         "sent %d at once" % (self._sent() - base))

    def test_an_answer_immediately_releases_the_next(self):
        # Self-clocking: throughput follows how fast the coordinator actually
        # replies, not a heartbeat that knows nothing about it.
        self._backlog(50)
        self.gateway.pump_reporting()
        sent = self._sent()
        self._reporting_result("reporting_failed", short_addr="0x10%02x" % 49,
                               reason="bind_failed")
        self.assertEqual(sent + 1, self._sent(), "an answer must free a credit")

    def test_a_thousand_devices_drain_without_a_burst_or_a_stall(self):
        # Scale is a queue-length question, and a queue entry is a dict. What
        # must not scale is the number in flight.
        base = self._backlog(1000)
        peak = 0
        for _ in range(400):
            self.gateway.pump_reporting()
            peak = max(peak, len(self.gateway._reporting_inflight))
            for ieee in list(self.gateway._reporting_inflight):
                self._reporting_result(
                    "reporting_configured", status="ok",
                    short_addr=self.gateway._registry[ieee]["short_addr"])
        self.assertLessEqual(peak, 4, "window exceeded (peak %d)" % peak)
        self.assertGreaterEqual(self._sent() - base, 1000,
                                "backlog never finished")

    def test_an_unanswered_request_does_not_leak_its_credit(self):
        # Otherwise a coordinator that swallows one request shrinks the window
        # permanently, and reporting quietly stops for the whole house.
        base = self._backlog(50)
        self.gateway.pump_reporting()
        self.assertEqual(4, self._sent() - base)

        self.gateway.pump_reporting()
        self.assertEqual(4, self._sent() - base,
                         "no answer yet, so no new sends")

        for ieee in list(self.gateway._reporting_inflight):
            self.gateway._reporting_inflight[ieee] = ticks_ms() - 1
        self.gateway.pump_reporting()
        self.assertEqual(8, self._sent() - base, "credits must be reclaimed")

    def test_longest_waiting_device_is_served_first(self):
        self._backlog(20)      # device n is more overdue than device n-1
        before = len(self.uart.written)
        self.gateway.pump_reporting()
        served = [m["payload"]["short_addr"]
                  for m in self.uart.written[before:]
                  if m["op"] == "enable_reporting"]
        expected = ["0x10%02x" % n for n in (19, 18, 17, 16)]
        self.assertEqual(expected, served,
                         "a waiting device must not be starved by newer ones")

    def test_retry_stops_once_reporting_is_confirmed(self):
        self.join_device()
        self._reporting_result("reporting_failed", reason="bind_failed")
        self._reporting_result("reporting_configured", status="ok")
        self.assertNotIn(IEEE, self.gateway._reporting_retry)

        after = self.written_ops().count("enable_reporting")
        self.gateway.pump_reporting()
        self.assertEqual(after, self.written_ops().count("enable_reporting"))
        device = self.gateway.devices()[IEEE]
        self.assertTrue(device["reporting"])
        self.assertNotIn("reporting_error", device)

    def _boot(self, *capabilities):
        self.uart.feed({"version": 1, "type": "event", "op": "boot",
                        "payload": {"firmware_version": "0.8.0",
                                    "capabilities": list(capabilities)}})

    def test_delivered_ack_counts_as_device_confirmation(self):
        self.join_device()
        self._boot("delivery_ack")
        self.uart.autoresponder = lambda m: [ack_for(m, status="delivered")]
        result = run(self.gateway.send(make_event("on")))
        self.assertEqual("confirmed_by_device", result["status"])

    def test_unproven_send_is_not_journalable_on_a_capable_coordinator(self):
        # The whole point: a coordinator that *can* prove delivery but did not
        # must not have its "ok" recorded as a completed schedule.
        from smart_kosher.ports.device_gateway import EXECUTION_SUCCESS_STATUSES
        self.join_device()
        self._boot("delivery_ack")
        self.uart.autoresponder = lambda m: [ack_for(m, status="ok")]
        result = run(self.gateway.send(make_event("on")))
        self.assertEqual("accepted_by_h2", result["status"])
        self.assertNotIn(result["status"], EXECUTION_SUCCESS_STATUSES)

    def test_an_explicit_failed_ack_is_never_treated_as_success(self):
        # Measured on hardware against a powered-off relay: the coordinator
        # answered `failed`, and because only reply["type"] == "error" was
        # checked, the ack fell through to sent_to_zigbee -- so the Executor
        # journaled a command that never reached the device and catch-up would
        # never retry it. The exact hole this whole ACK ladder exists to close.
        from smart_kosher.ports.device_gateway import EXECUTION_SUCCESS_STATUSES
        self.join_device()
        self.uart.autoresponder = lambda m: [
            ack_for(m, status="failed", payload={"aps_status": 233})]

        result = run(self.gateway.send(make_event("off")))
        self.assertEqual("error", result["status"])
        self.assertNotIn(result["status"], EXECUTION_SUCCESS_STATUSES)
        self.assertIn("233", result["error"])

    def test_a_failed_ack_fails_even_before_capabilities_are_known(self):
        # A gateway that has not pinged yet has no capability list. The verdict
        # must come from the ack itself, not from what we have learned so far.
        self.join_device()
        self.assertEqual((), self.gateway._capabilities)
        self.uart.autoresponder = lambda m: [ack_for(m, status="failed")]
        self.assertEqual("error", run(self.gateway.send(make_event("on")))["status"])

    def test_a_successful_ping_survives_a_delivery_capable_coordinator(self):
        # ping is the coordinator answering about itself -- there is no device
        # to confirm it. Running it through the delivery ladder made a good
        # ping look like a failure, and ping() then latched the breaker open
        # permanently: after one glitch the link never recovered.
        self._boot("delivery_ack")
        self.uart.autoresponder = lambda m: [ack_for(m, status="pong")]
        self.gateway._down = True

        result = run(self.gateway.ping())
        self.assertEqual("sent_to_zigbee", result["status"])
        self.assertFalse(self.gateway._down, "breaker stayed latched open")

    def test_old_firmware_keeps_its_existing_semantics(self):
        # Product B's NanoC6 stays on the older build; tightening the rule for
        # it would stop every schedule there from ever being journaled.
        self.join_device()
        self._boot()                       # no capabilities advertised
        self.uart.autoresponder = lambda m: [ack_for(m, status="ok")]
        result = run(self.gateway.send(make_event("on")))
        self.assertEqual("sent_to_zigbee", result["status"])

    def test_group_is_only_as_proven_as_its_weakest_member(self):
        self.repo.upsert("endpoints", {"id": "ep2", "name": "second",
                                       "ieee_address": "aa:bb:cc:dd:ee:ff:00:11"})
        self.repo.upsert("groups", {"id": "g1", "name": "all",
                                    "member_ids": ["ep1", "ep2"]})
        self.join_device()
        self.join_device(ieee="aa:bb:cc:dd:ee:ff:00:11", short="0x0002")
        self._boot("delivery_ack")

        def reply(msg):
            if msg["op"] != "on_off":
                return [ack_for(msg)]
            proven = msg["payload"]["short_addr"] == SHORT
            return [ack_for(msg, status="delivered" if proven else "ok")]

        self.uart.autoresponder = reply
        result = run(self.gateway.send(
            make_event("on", target_type="group", target_id="g1")))
        self.assertEqual("accepted_by_h2", result["status"])

    def test_discovered_endpoints_are_recorded(self):
        # device_joined can only ever say "endpoint 1"; a two-gang switch needs
        # the list the coordinator discovers afterwards.
        self.join_device()
        self.uart.feed({"version": 1, "type": "event", "op": "device_endpoints",
                        "payload": {"short_addr": SHORT, "endpoints": [1, 2]}})
        self.assertEqual([1, 2], self.gateway.devices()[IEEE]["endpoints"])

    def test_discovered_clusters_are_recorded_per_endpoint(self):
        # Cluster discovery outlived the measurement feature it was built for:
        # it is how a two-gang switch's second endpoint is known to speak OnOff
        # at all, rather than being assumed from the model number.
        self.join_device()
        self.uart.feed({"version": 1, "type": "event", "op": "device_clusters",
                        "payload": {"short_addr": SHORT, "endpoint": 2,
                                    "in_clusters": [0x0000, 0x0006]}})
        device = self.gateway.devices()[IEEE]
        self.assertEqual([0, 6], device["clusters"]["2"])

    def test_measurement_clusters_are_never_asked_to_report(self):
        # Electrical measurement was removed (2026-08-05). A relay that still
        # advertises the metering clusters must be left alone: asking would
        # reopen the failure that used to knock healthy devices out of
        # reporting, for a feature the product no longer has.
        self.join_device()
        before = len([m for m in self.uart.written
                      if m["op"] == "enable_reporting"])
        self.uart.feed({"version": 1, "type": "event", "op": "device_clusters",
                        "payload": {"short_addr": SHORT, "endpoint": 1,
                                    "in_clusters": [0x0006, 0x0B04, 0x0702]}})
        asked = [m for m in self.uart.written
                 if m["op"] == "enable_reporting"][before:]
        self.assertEqual([], asked)
        self.assertNotIn("measures", self.gateway.devices()[IEEE])
        self.assertNotIn("measurements", self.gateway.devices()[IEEE])

    def test_a_stray_measurement_report_is_ignored(self):
        # A coordinator still running 0.11.x can send these. They must be
        # dropped without touching the on/off state -- power flowing is not the
        # same claim as "the relay is on".
        self.join_device()
        self.uart.feed(report_event(True))
        self.uart.feed({"version": 1, "type": "event",
                        "op": "measurement_report",
                        "payload": {"short_addr": SHORT, "endpoint": 1,
                                    "cluster": 0x0B04, "active_power": 0}})
        device = self.gateway.devices()[IEEE]
        self.assertTrue(device["on_off"])
        self.assertNotIn("measurements", device)

    def test_device_left_removes_it_from_the_registry(self):
        self.join_device()
        self.assertIn(IEEE, self.gateway.devices())
        self.uart.feed({"version": 1, "type": "event", "op": "device_left",
                        "payload": {"ieee_addr": IEEE, "short_addr": SHORT,
                                    "rejoin": False}})
        self.assertNotIn(IEEE, self.gateway.devices())

    def test_leave_for_rejoin_keeps_the_device_but_marks_it_unreachable(self):
        self.join_device()
        self.uart.feed({"version": 1, "type": "event", "op": "device_left",
                        "payload": {"ieee_addr": IEEE, "short_addr": SHORT,
                                    "rejoin": True}})
        device = self.gateway.devices().get(IEEE)
        self.assertIsNotNone(device, "a device coming right back is not gone")
        self.assertTrue(device["unreachable"])

    def test_network_down_event_clears_the_link_claim(self):
        self._boot("delivery_ack")
        self.assertTrue(self.gateway.status_info()["network_up"])
        self.uart.feed({"version": 1, "type": "event", "op": "network_down",
                        "payload": {}})
        self.assertFalse(self.gateway.status_info()["network_up"])

    def test_rejoin_clears_a_stale_reporting_error(self):
        self.join_device()
        self._reporting_result("reporting_failed", reason="bind_failed")
        self.join_device()      # device power-cycled and announced again
        self._reporting_result("reporting_configured", status="ok")
        self.assertTrue(self.gateway.devices()[IEEE]["reporting"])
        self.assertNotIn("reporting_error", self.gateway.devices()[IEEE])

    def test_a_commanded_state_survives_the_next_poll(self):
        # The bug users see: tap off, the UI shows off, then the 3-second poll
        # reads a report from *before* the command and flips it back on, then
        # the real report lands and it goes off again.
        self.join_device()
        self.uart.feed(report_event(True))          # device is on
        self.uart.autoresponder = lambda m: [ack_for(m)]

        run(self.gateway.send(make_event("off")))
        self.assertFalse(self.gateway.devices()[IEEE]["on_off"],
                         "a poll right after the command must not show 'on'")

        self.uart.feed(report_event(False))         # device confirms
        self.assertFalse(self.gateway.devices()[IEEE]["on_off"])
        self.assertNotIn(IEEE, self.gateway._expected, "expectation not cleared")

    def test_a_failed_command_does_not_claim_the_new_state(self):
        self.join_device()
        self.uart.feed(report_event(True))
        self.uart.autoresponder = None              # never acked
        run(self.gateway.send(make_event("off")))
        self.assertTrue(self.gateway.devices()[IEEE]["on_off"],
                        "an unsent command must not change what we show")

    def test_the_device_own_word_overrides_what_we_expected(self):
        # Someone flips the physical switch back straight after our command.
        self.join_device()
        self.uart.autoresponder = lambda m: [ack_for(m)]
        run(self.gateway.send(make_event("on")))
        self.uart.feed(report_event(False))
        self.assertFalse(self.gateway.devices()[IEEE]["on_off"])

    def test_expectation_never_leaks_into_observed_state(self):
        # wait_for_report's whole value is that _states is the device talking,
        # never something we merely believe.
        self.join_device()
        self.uart.autoresponder = lambda m: [ack_for(m)]
        run(self.gateway.send(make_event("on")))
        self.assertNotIn(IEEE, self.gateway._states)
        confirmation = run(self.gateway.wait_for_report(IEEE, True, 10))
        self.assertFalse(confirmation["confirmed"],
                         "our own command must not count as the device's word")

    def test_attribute_report_updates_state_by_stable_ieee(self):
        self.join_device()
        self.uart.feed(report_event(True))
        device = self.gateway.devices()[IEEE]
        self.assertTrue(device["on_off"])
        self.assertIn("state_age_ms", device)

    def test_registry_survives_reboot_via_file(self):
        path = os.path.join(tempfile.mkdtemp(), "zigbee_devices.json")
        gw1 = ZigbeeGateway(self.uart, self.repo, registry_path=path,
                            ack_timeout_ms=80, log=lambda *a: None)
        self.uart.deliver = gw1.process_line
        self.uart.feed(joined_event())

        gw2 = ZigbeeGateway(FakeUart(), self.repo, registry_path=path,
                            ack_timeout_ms=80, log=lambda *a: None)
        self.assertIn(IEEE, gw2.devices())
        self.assertEqual(SHORT, gw2.devices()[IEEE]["short_addr"])

    def test_corrupt_and_noise_lines_are_skipped(self):
        self.assertFalse(self.gateway.process_line(
            b"boot noise from the console\n"))
        self.assertFalse(self.gateway.process_line(
            b"deadbeef {\"not\": \"matching crc\"}\n"))
        self.assertTrue(self.uart.feed(joined_event()))
        self.assertIn(IEEE, self.gateway.devices())


class DeviceRemovalTests(GatewayTestCase):
    """Deleting a device on the panel must evict it from the mesh too."""

    def setUp(self):
        super().setUp()
        from smart_kosher.adapters import SettingsStore
        from smart_kosher.application.api import Api
        from smart_kosher.application.control_service import ControlService
        from smart_kosher.application.crud_service import CrudService
        from smart_kosher.application.device_time import DeviceTimeService
        from smart_kosher.application.views import ViewService
        journal = MemoryEventJournal()
        crud = CrudService(self.repo)
        self.api = Api(
            crud, ControlService(Executor(self.gateway, journal), self.repo),
            # Geography only. candle_offset/tzais_offset used to be seeded here
            # too; they are not settings any more (candle lighting is a
            # constant, Shabbat exit is an angle) and the API drops them on
            # read, so carrying them just left numbers no part of the system
            # holds sitting in a fixture, waiting to be believed.
            SettingsStore("/nonexistent-settings.json",
                          defaults={"lat": 31.77, "lon": 35.21,
                                    "elevation": 779,
                                    "utc_offset_minutes": 120,
                                    "in_israel": True}),
            views=ViewService(self.repo), device_time=DeviceTimeService(None),
            zigbee=self.gateway)
        self.join_device()

    def written_removals(self):
        return [m for m in self.uart.written if m["op"] == "remove_device"]

    def test_deleting_the_endpoint_removes_the_device_from_the_network(self):
        # It used to delete only this hub's record: the device stayed joined,
        # kept its slot among the coordinator's children, and came back into
        # the registry the next time it announced itself.
        run(self.api.dispatch("endpoints.delete", {"id": "ep1"}))
        self.assertEqual(1, len(self.written_removals()))
        self.assertEqual(IEEE, self.written_removals()[0]["payload"]["ieee_addr"])
        self.assertNotIn(IEEE, self.gateway.devices())

    def test_one_gang_of_a_two_gang_switch_does_not_evict_the_device(self):
        # Two entities, one radio. Deleting one must leave the other working.
        self.repo.upsert("endpoints", {"id": "ep1b", "name": "gang 2",
                                       "ieee_address": IEEE,
                                       "zigbee_endpoint": 2})
        run(self.api.dispatch("endpoints.delete", {"id": "ep1"}))
        self.assertEqual([], self.written_removals(),
                         "the second gang still needs this device")
        self.assertIn(IEEE, self.gateway.devices())

        run(self.api.dispatch("endpoints.delete", {"id": "ep1b"}))
        self.assertEqual(1, len(self.written_removals()),
                         "the last endpoint should release the device")

    def test_deleting_an_unpaired_endpoint_touches_no_radio(self):
        self.repo.upsert("endpoints", {"id": "ep_none", "name": "no radio"})
        run(self.api.dispatch("endpoints.delete", {"id": "ep_none"}))
        self.assertEqual([], self.written_removals())


class ObservedStateTests(GatewayTestCase):
    def _control(self):
        executor = Executor(self.gateway, MemoryEventJournal())
        return ControlService(executor, self.repo)

    def test_confirmation_arrives_from_attribute_report(self):
        self.join_device()
        self.uart.autoresponder = lambda m: (
            [ack_for(m), report_event(True)] if m["op"] == "on_off"
            else [ack_for(m)])

        outcome = run(self._control().send(
            "endpoint", "ep1", "on", confirm_ms=200))

        self.assertEqual("executed", outcome["status"])
        self.assertEqual({"confirmed": True, "observed": True},
                         outcome["confirmation"])

    def test_no_report_within_window_is_unconfirmed(self):
        self.join_device()
        self.uart.autoresponder = lambda m: [ack_for(m)]

        outcome = run(self._control().send(
            "endpoint", "ep1", "off", confirm_ms=60))

        self.assertEqual("executed", outcome["status"])
        self.assertFalse(outcome["confirmation"]["confirmed"])

    def test_confirmation_skipped_without_gateway_support(self):
        # e.g. H2Simulator in dev: no wait_for_report attribute
        from smart_kosher.adapters import H2Simulator
        executor = Executor(H2Simulator(["sent_to_zigbee"]),
                            MemoryEventJournal())
        control = ControlService(executor, self.repo)
        outcome = run(control.send("endpoint", "ep1", "on", confirm_ms=200))
        self.assertEqual("executed", outcome["status"])
        self.assertNotIn("confirmation", outcome)


class MaintenanceOpsTests(GatewayTestCase):
    def test_ping_updates_liveness_info(self):
        self.uart.autoresponder = lambda m: [{
            "version": 1, "type": "ack", "op": "ping",
            "request_id": m["request_id"], "status": "pong",
            "payload": {"firmware": "smart_kosher_h2_coordinator",
                        "firmware_version": "0.7.0", "target": "esp32c6",
                        "network_up": True}}]
        result = run(self.gateway.ping())
        self.assertEqual("sent_to_zigbee", result["status"])
        self.assertTrue(self.gateway.info["network_up"])
        self.assertEqual("esp32c6", self.gateway.info["target"])
        self.assertEqual("0.7.0",
                         self.gateway.status_info()["firmware_version"])

    def test_permit_join_passes_duration(self):
        self.uart.autoresponder = lambda m: [ack_for(m)]
        result = run(self.gateway.permit_join(180))
        self.assertEqual("sent_to_zigbee", result["status"])
        cmd = self.uart.written[-1]
        self.assertEqual("permit_join", cmd["op"])
        self.assertEqual({"duration": 180}, cmd["payload"])

    def test_forget_device_clears_registry_and_notifies_coordinator(self):
        self.join_device()
        out = self.gateway.forget_device(IEEE)
        self.assertTrue(out["removed"])
        self.assertNotIn(IEEE, self.gateway.devices())
        cmd = self.uart.written[-1]
        self.assertEqual("remove_device", cmd["op"])
        self.assertEqual(IEEE, cmd["payload"]["ieee_addr"])


class ExecutorIntegrationTests(GatewayTestCase):
    def test_executor_journals_success_through_real_contract(self):
        self.join_device()
        self.uart.autoresponder = lambda m: [ack_for(m)]
        executor = Executor(self.gateway, MemoryEventJournal())

        outcome = run(executor.execute(make_event("on")))

        self.assertEqual("executed", outcome["status"])
        self.assertEqual("sent_to_zigbee",
                         outcome["gateway_result"]["status"])

    def test_executor_retries_timeout_then_succeeds(self):
        self.join_device()
        calls = {"n": 0}

        def flaky(m):
            if m["op"] != "on_off":
                return [ack_for(m)]
            calls["n"] += 1
            return [ack_for(m)] if calls["n"] > 1 else None
        self.uart.autoresponder = flaky
        executor = Executor(self.gateway, MemoryEventJournal())

        outcome = run(executor.execute(make_event("on")))

        self.assertEqual("executed", outcome["status"])
        self.assertEqual(2, outcome["attempts"])


if __name__ == "__main__":
    unittest.main()
