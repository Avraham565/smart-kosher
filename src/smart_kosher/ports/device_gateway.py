"""Port used by the executor to deliver device commands."""


class DeviceGateway:
    def send(self, event):
        """Return dict: {status: ack|timeout|error, event_id}"""
        raise NotImplementedError
