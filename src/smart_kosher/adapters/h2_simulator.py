"""Deterministic DeviceGateway simulator for application tests.

This simulator uses the DeviceGateway internal status contract. It intentionally
skips UART framing, Zigbee network state, joining, and device addressing. Use
firmware/h2_coordinator for hardware-proven behavior.
"""

from ..domain._values import clone_json
from ..domain.events import validate_event
from ..ports.device_gateway import GATEWAY_ALL_STATUSES, DeviceGateway


class H2Simulator(DeviceGateway):
    def __init__(self, responses=None):
        # Each entry is a status string or a full result dict.
        self._responses = list(responses or [])
        # All events delivered so far, in order.
        self.commands = []

    def queue_response(self, status, **details):
        if status not in GATEWAY_ALL_STATUSES:
            raise ValueError("unknown status: {}".format(status))
        result = {"status": status}
        result.update(details)
        self._responses.append(result)

    async def send(self, event):
        validate_event(event)
        self.commands.append(clone_json(event))

        if self._responses:
            result = self._responses.pop(0)
            if isinstance(result, str):
                result = {"status": result}
        else:
            result = {"status": "sent_to_zigbee"}

        result = dict(result)
        result.setdefault("command_id", event["event_id"])
        return clone_json(result)
