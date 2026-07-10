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
from smart_kosher.adapters.zigbee_gateway import ZigbeeGateway
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
