"""Port used by the executor to deliver device commands."""

# Gateway adapters normalize transport-specific replies into these statuses.
# ZigbeeGateway._ack_status does exactly that for the H2/NanoC6 coordinator:
# the wire's own ACK ladder (docs/UART_PROTOCOL.md) maps onto these names, and
# a coordinator too old to distinguish delivered from accepted keeps the older,
# looser meaning of status="ok" -> sent_to_zigbee.
DELIVERY_SUCCESS_STATUSES = frozenset(
    {"accepted_by_h2", "sent_to_zigbee", "confirmed_by_device", "observed_state"}
)

# Transient failures: Executor will retry.
GATEWAY_RETRY_STATUSES = frozenset({"timeout", "error"})

# Every status the gateway layer may legally return.
GATEWAY_ALL_STATUSES = DELIVERY_SUCCESS_STATUSES | GATEWAY_RETRY_STATUSES

# Subset that counts as "event executed" in the journal.
# accepted_by_h2 is only proof that a transport accepted a request, not that a
# device command reached or affected a target device.
EXECUTION_SUCCESS_STATUSES = frozenset(
    {"sent_to_zigbee", "confirmed_by_device", "observed_state"}
)


class DeviceGateway:
    async def send(self, event):
        """Deliver one event (async — a radio round-trip is I/O).

        Return a dict with at least:
          status     - one of GATEWAY_ALL_STATUSES
          command_id - identifier used by the gateway for correlation
        """
        raise NotImplementedError
