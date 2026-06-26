"""ZigbeeGateway — real UART adapter, S3 ↔ H2 (UART_PROTOCOL.md).

UART transport contract (two methods required):
    uart.write(data: bytes)                    — write raw bytes to the line
    uart.readline(timeout_ms: int) -> bytes    — one line including \\n; b'' or None on timeout

MicroPython (S3, production):
    from machine import UART
    uart = UART(1, baudrate=115200, tx=5, rx=19, rxbuf=512, timeout=3000)
    # readline(timeout_ms) wraps: lambda ms: uart.readline() or b''

PC / pyserial (integration tests with real H2 on COM port):
    import serial
    ser = serial.Serial("COM6", 115200, timeout=3)
    # wrap readline: lambda ms: ser.readline()
"""

from .uart_codec import decode, encode
from ..ports.device_gateway import EXECUTION_SUCCESS_STATUSES, DeviceGateway

# genOnOff cluster (0x0006): standard ZCL commands for all Sonoff relay devices.
_ACTION_TO_ZCL = {
    "on":     (6, 1),
    "off":    (6, 0),
    "toggle": (6, 2),
}


class ZigbeeGateway(DeviceGateway):
    """Translates domain events to UART zcl_command messages and reads ACKs."""

    def __init__(self, uart, repository, timeout_ms=3000):
        self._uart = uart
        self._repo = repository
        self._timeout_ms = timeout_ms
        self._seq = 0

    def send(self, event):
        targets = self._resolve_targets(event)
        if not targets:
            return {
                "status": "error",
                "error": "no_zigbee_targets",
                "command_id": event["event_id"],
            }
        last = None
        for ieee, ep_num in targets:
            last = self._send_one(event, ieee, ep_num)
            if last["status"] not in EXECUTION_SUCCESS_STATUSES:
                return last  # fail fast on first error / timeout
        return last

    # ------------------------------------------------------------------ #
    # Private                                                              #
    # ------------------------------------------------------------------ #

    def _resolve_targets(self, event):
        target_type = event["target_type"]
        target_id = event["target_id"]
        if target_type == "endpoint":
            return self._ep_targets(target_id)
        if target_type == "group":
            group = self._repo.get_by_id("groups", target_id)
            if group is None:
                return []
            result = []
            for mid in group.get("member_ids", []):
                result.extend(self._ep_targets(mid))
            return result
        return []

    def _ep_targets(self, endpoint_id):
        ep = self._repo.get_by_id("endpoints", endpoint_id)
        if ep is None:
            return []
        ieee = ep.get("ieee_address")
        ep_num = ep.get("zigbee_endpoint")
        if not ieee or ep_num is None:
            return []
        return [(ieee, ep_num)]

    def _send_one(self, event, ieee, ep_num):
        action = event["action_type"]
        if action not in _ACTION_TO_ZCL:
            return {"status": "error", "error": "unsupported_action",
                    "command_id": event["event_id"]}
        cluster, command = _ACTION_TO_ZCL[action]
        self._seq += 1
        request_id = "r{}".format(self._seq)
        command_id = "{}_{}_ep{}".format(event["event_id"], ieee, ep_num)

        msg = {
            "version": 1,
            "request_id": request_id,
            "command_id": command_id,
            "type": "cmd",
            "op": "zcl_command",
            "payload": {
                "ieee": ieee,
                "endpoint": ep_num,
                "cluster": cluster,
                "command": command,
                "args": {},
            },
        }
        self._uart.write(encode(msg))

        raw = self._uart.readline(self._timeout_ms)
        if not raw:
            return {"status": "timeout", "command_id": command_id}
        try:
            ack = decode(raw)
        except ValueError as exc:
            return {"status": "error", "error": str(exc), "command_id": command_id}
        if (
            ack.get("type") != "ack"
            or ack.get("request_id") != request_id
            or ack.get("command_id") != command_id
        ):
            return {"status": "error", "error": "unexpected_response", "command_id": command_id}
        return {
            "status": ack.get("status", "error"),
            "command_id": ack.get("command_id", command_id),
        }
