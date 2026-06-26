"""Tests for ZigbeeGateway — UART adapter that translates events to zcl_command."""

import unittest

from smart_kosher.adapters import uart_decode, uart_encode
from smart_kosher.adapters.zigbee_gateway import ZigbeeGateway
from smart_kosher.adapters.memory_repository import MemoryRepository


IEEE = "0x00158d0001234567"
IEEE2 = "0x00158d0001234568"


class MockUart:
    """Simulates the UART line: queues raw response bytes, records written bytes."""

    def __init__(self, responses=None):
        self._responses = list(responses or [])
        self.written = []

    def write(self, data):
        self.written.append(data)

    def readline(self, timeout_ms):
        return self._responses.pop(0) if self._responses else None

    def last_command(self):
        """Decode and return the last zcl_command sent over UART."""
        return uart_decode(self.written[-1])


def _command_id(event_id="ctrl_test", ieee=IEEE, ep_num=1):
    return "{}_{}_ep{}".format(event_id, ieee, ep_num)


def _ack(status="sent_to_zigbee", command_id=None, request_id="r1"):
    if command_id is None:
        command_id = _command_id()
    return uart_encode({
        "version": 1,
        "request_id": request_id,
        "command_id": command_id,
        "type": "ack",
        "status": status,
    })


def _repo_with_endpoint(ep_id="ep-1", ieee=IEEE, ep_num=1):
    repo = MemoryRepository()
    repo.upsert("endpoints", {
        "id": ep_id,
        "name": "מנורה",
        "ieee_address": ieee,
        "zigbee_endpoint": ep_num,
    })
    return repo


def _event(target_type="endpoint", target_id="ep-1", action_type="on"):
    return {
        "event_id": "ctrl_test",
        "schedule_id": "manual",
        "source_date": (2026, 6, 18),
        "utc_minute": 600,
        "target_type": target_type,
        "target_id": target_id,
        "action_type": action_type,
        "action_data": {},
    }


class TestSingleEndpoint(unittest.TestCase):
    def _gw(self, responses=None):
        uart = MockUart(responses or [_ack()])
        repo = _repo_with_endpoint()
        return ZigbeeGateway(uart, repo), uart

    def test_on_sends_cluster6_command1(self):
        gw, uart = self._gw()
        gw.send(_event(action_type="on"))
        payload = uart.last_command()["payload"]
        self.assertEqual(6, payload["cluster"])
        self.assertEqual(1, payload["command"])

    def test_off_sends_cluster6_command0(self):
        gw, uart = self._gw()
        gw.send(_event(action_type="off"))
        payload = uart.last_command()["payload"]
        self.assertEqual(6, payload["cluster"])
        self.assertEqual(0, payload["command"])

    def test_toggle_sends_cluster6_command2(self):
        gw, uart = self._gw()
        gw.send(_event(action_type="toggle"))
        payload = uart.last_command()["payload"]
        self.assertEqual(6, payload["cluster"])
        self.assertEqual(2, payload["command"])

    def test_sent_message_contains_ieee_and_endpoint(self):
        gw, uart = self._gw()
        gw.send(_event())
        payload = uart.last_command()["payload"]
        self.assertEqual(IEEE, payload["ieee"])
        self.assertEqual(1, payload["endpoint"])

    def test_sent_message_is_zcl_command_type(self):
        gw, uart = self._gw()
        gw.send(_event())
        msg = uart.last_command()
        self.assertEqual("cmd", msg["type"])
        self.assertEqual("zcl_command", msg["op"])

    def test_sent_message_contains_command_id(self):
        gw, uart = self._gw()
        gw.send(_event())
        self.assertEqual(_command_id(), uart.last_command()["command_id"])

    def test_success_returns_sent_to_zigbee(self):
        gw, uart = self._gw([_ack(status="sent_to_zigbee")])
        result = gw.send(_event())
        self.assertEqual("sent_to_zigbee", result["status"])

    def test_returns_command_id_from_ack(self):
        gw, uart = self._gw()
        result = gw.send(_event())
        self.assertEqual(_command_id(), result["command_id"])

    def test_timeout_returns_timeout_status(self):
        uart = MockUart([None])  # no response
        repo = _repo_with_endpoint()
        gw = ZigbeeGateway(uart, repo)
        result = gw.send(_event())
        self.assertEqual("timeout", result["status"])

    def test_bad_crc_in_ack_returns_error(self):
        bad = b"00000000 " + _ack()[9:]  # corrupt the CRC
        uart = MockUart([bad])
        repo = _repo_with_endpoint()
        gw = ZigbeeGateway(uart, repo)
        result = gw.send(_event())
        self.assertEqual("error", result["status"])
        self.assertIn("bad_crc", result["error"])

    def test_unexpected_response_type_returns_error(self):
        event_line = uart_encode({
            "version": 1,
            "h2_event_id": 7,
            "type": "event",
            "op": "boot",
            "payload": {"boot_id": 2, "firmware_version": "0.1.0"},
        })
        uart = MockUart([event_line])
        repo = _repo_with_endpoint()
        gw = ZigbeeGateway(uart, repo)
        result = gw.send(_event())
        self.assertEqual("error", result["status"])
        self.assertEqual("unexpected_response", result["error"])

    def test_mismatched_request_id_returns_error(self):
        uart = MockUart([_ack(request_id="old")])
        repo = _repo_with_endpoint()
        gw = ZigbeeGateway(uart, repo)
        result = gw.send(_event())
        self.assertEqual("error", result["status"])
        self.assertEqual("unexpected_response", result["error"])

    def test_mismatched_command_id_returns_error(self):
        uart = MockUart([_ack(command_id="other_command")])
        repo = _repo_with_endpoint()
        gw = ZigbeeGateway(uart, repo)
        result = gw.send(_event())
        self.assertEqual("error", result["status"])
        self.assertEqual("unexpected_response", result["error"])

    def test_accepted_by_h2_is_not_a_success(self):
        # accepted_by_h2 is valid ACK for bootstrap ops, but zcl_command expects sent_to_zigbee
        uart = MockUart([_ack(status="accepted_by_h2")])
        repo = _repo_with_endpoint()
        gw = ZigbeeGateway(uart, repo)
        result = gw.send(_event())
        self.assertEqual("accepted_by_h2", result["status"])  # returned as-is
        # The Executor will NOT record this as executed (EXECUTION_SUCCESS_STATUSES check)


class TestMissingZigbeeData(unittest.TestCase):
    def test_endpoint_without_ieee_returns_error(self):
        repo = MemoryRepository()
        repo.upsert("endpoints", {"id": "ep-1", "name": "מנורה", "zigbee_endpoint": 1})
        gw = ZigbeeGateway(MockUart(), repo)
        result = gw.send(_event())
        self.assertEqual("error", result["status"])
        self.assertEqual("no_zigbee_targets", result["error"])

    def test_endpoint_without_zigbee_ep_returns_error(self):
        repo = MemoryRepository()
        repo.upsert("endpoints", {"id": "ep-1", "name": "מנורה", "ieee_address": IEEE})
        gw = ZigbeeGateway(MockUart(), repo)
        result = gw.send(_event())
        self.assertEqual("error", result["status"])

    def test_unknown_endpoint_returns_error(self):
        repo = MemoryRepository()
        gw = ZigbeeGateway(MockUart(), repo)
        result = gw.send(_event(target_id="ep-ghost"))
        self.assertEqual("error", result["status"])


class TestGroup(unittest.TestCase):
    def _repo_with_group(self):
        repo = _repo_with_endpoint("ep-1", IEEE, 1)
        repo.upsert("endpoints", {
            "id": "ep-2", "name": "פנס",
            "ieee_address": IEEE2, "zigbee_endpoint": 1,
        })
        repo.upsert("groups", {
            "id": "grp-1", "name": "סלון", "member_ids": ["ep-1", "ep-2"],
        })
        return repo

    def test_group_sends_one_command_per_member(self):
        repo = self._repo_with_group()
        uart = MockUart([_ack(), _ack(command_id=_command_id(ieee=IEEE2), request_id="r2")])
        gw = ZigbeeGateway(uart, repo)
        gw.send(_event(target_type="group", target_id="grp-1"))
        self.assertEqual(2, len(uart.written))

    def test_group_sends_to_correct_ieee_addresses(self):
        repo = self._repo_with_group()
        uart = MockUart([_ack(), _ack(command_id=_command_id(ieee=IEEE2), request_id="r2")])
        gw = ZigbeeGateway(uart, repo)
        gw.send(_event(target_type="group", target_id="grp-1"))
        iee_sent = {uart_decode(line)["payload"]["ieee"] for line in uart.written}
        self.assertEqual({IEEE, IEEE2}, iee_sent)

    def test_group_command_ids_are_unique_per_zigbee_endpoint(self):
        repo = _repo_with_endpoint("ep-1", IEEE, 1)
        repo.upsert("endpoints", {
            "id": "ep-2", "name": "channel 2",
            "ieee_address": IEEE, "zigbee_endpoint": 2,
        })
        repo.upsert("groups", {
            "id": "grp-1", "name": "both channels", "member_ids": ["ep-1", "ep-2"],
        })
        uart = MockUart([
            _ack(command_id=_command_id(ieee=IEEE, ep_num=1), request_id="r1"),
            _ack(command_id=_command_id(ieee=IEEE, ep_num=2), request_id="r2"),
        ])
        gw = ZigbeeGateway(uart, repo)
        gw.send(_event(target_type="group", target_id="grp-1"))
        ids = [uart_decode(line)["command_id"] for line in uart.written]
        self.assertEqual([_command_id(ieee=IEEE, ep_num=1),
                          _command_id(ieee=IEEE, ep_num=2)], ids)

    def test_group_stops_on_first_timeout(self):
        repo = self._repo_with_group()
        uart = MockUart([None])  # first response: timeout
        gw = ZigbeeGateway(uart, repo)
        result = gw.send(_event(target_type="group", target_id="grp-1"))
        self.assertEqual("timeout", result["status"])
        self.assertEqual(1, len(uart.written))  # second endpoint never sent

    def test_unknown_group_returns_error(self):
        repo = MemoryRepository()
        gw = ZigbeeGateway(MockUart(), repo)
        result = gw.send(_event(target_type="group", target_id="grp-ghost"))
        self.assertEqual("error", result["status"])


class TestUartWireFormat(unittest.TestCase):
    """Verify the bytes on the wire match UART_PROTOCOL.md exactly."""

    def test_sent_line_ends_with_newline(self):
        uart = MockUart([_ack()])
        gw = ZigbeeGateway(uart, _repo_with_endpoint())
        gw.send(_event())
        self.assertTrue(uart.written[0].endswith(b"\n"))

    def test_sent_line_has_valid_crc(self):
        uart = MockUart([_ack()])
        gw = ZigbeeGateway(uart, _repo_with_endpoint())
        gw.send(_event())
        decoded = uart_decode(uart.written[0])  # raises if CRC bad
        self.assertIsInstance(decoded, dict)

    def test_request_id_increments_across_calls(self):
        uart = MockUart([_ack(), _ack(request_id="r2")])
        gw = ZigbeeGateway(uart, _repo_with_endpoint())
        gw.send(_event())
        gw.send(_event())
        r1 = uart_decode(uart.written[0])["request_id"]
        r2 = uart_decode(uart.written[1])["request_id"]
        self.assertNotEqual(r1, r2)


if __name__ == "__main__":
    unittest.main()
