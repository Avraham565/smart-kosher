"""Port used by the executor to deliver device commands."""

# Gateway adapters normalize transport-specific replies into these statuses.
# The current hardware experiment returns simpler ACKs such as status="ok";
# a production adapter should map those replies into this internal contract.
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
