"""Port used by the executor to deliver device commands."""


class DeviceGateway:
    def send(self, event):
        """Return a result dict whose status is ack, timeout, or error."""
        raise NotImplementedError
