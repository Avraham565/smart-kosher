"""Port used by the executor to deliver device commands."""

# All four ACK statuses the H2 firmware can return (UART_PROTOCOL.md §ACK Status).
UART_ACK_STATUSES = frozenset(
    {"accepted_by_h2", "sent_to_zigbee", "confirmed_by_device", "observed_state"}
)
# Transient failures — Executor will retry.
GATEWAY_RETRY_STATUSES = frozenset({"timeout", "error"})
# Every status the gateway layer may legally return.
GATEWAY_ALL_STATUSES = UART_ACK_STATUSES | GATEWAY_RETRY_STATUSES
# Subset that counts as "event executed" in the journal.
# accepted_by_h2 is excluded: it is valid for bootstrap commands (coordinator_start
# etc.) but never sufficient proof that a zcl_command reached the device.
EXECUTION_SUCCESS_STATUSES = frozenset(
    {"sent_to_zigbee", "confirmed_by_device", "observed_state"}
)


class DeviceGateway:
    def send(self, event):
        """Deliver one event.  Return dict with at least:
          status     — one of GATEWAY_ALL_STATUSES
          command_id — echoed from the request
        """
        raise NotImplementedError
