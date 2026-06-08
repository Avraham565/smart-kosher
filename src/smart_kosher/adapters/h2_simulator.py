"""Deterministic ESP32-H2 gateway simulator.

It never claims to control hardware. Tests can queue ack, timeout, or error
responses and inspect all delivered commands.
"""

from ..domain._values import clone_json
from ..domain.events import validate_event
from ..ports.device_gateway import DeviceGateway


class H2Simulator(DeviceGateway):
    def __init__(self, responses=None):
        self._responses = list(responses or [])
        self.commands = []

    def queue_response(self, status, **details):
        result = {"status": status}
        result.update(details)
        self._responses.append(result)

    def send(self, event):
        validate_event(event)
        self.commands.append(clone_json(event))
        if self._responses:
            result = self._responses.pop(0)
            if isinstance(result, str):
                result = {"status": result}
            return clone_json(result)
        return {"status": "ack", "event_id": event["event_id"]}
