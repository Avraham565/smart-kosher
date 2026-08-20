"""Idempotent event execution with bounded retries."""

from ..domain._values import is_integer
from ..domain.events import validate_event
from ..ports.device_gateway import EXECUTION_SUCCESS_STATUSES, GATEWAY_ALL_STATUSES

# The executor's outcome vocabulary: what execute() concluded about an event.
#
# Deliberately *not* the gateway's ladder in ports/device_gateway.py. That one
# says how far a command travelled on the wire; this one says what the brain
# decided about the event afterwards. Merging them would put "the radio took
# it" and "stop retrying" in one set, which are different questions.
#
# Callers import these rather than restating the strings, so a rename here
# reaches them instead of quietly splitting into two vocabularies that happen
# to agree. The values themselves are a contract past this module -- they
# leave over REST and the panel UI reads them -- so both the names and the
# values are pinned by tests/test_executor_status_vocabulary.py.
EXECUTED = "executed"
ALREADY_EXECUTED = "already_executed"
ACK_UNJOURNALED = "ack_unjournaled"
FAILED = "failed"


class Executor:
    def __init__(self, gateway, journal, max_attempts=3):
        if not is_integer(max_attempts) or max_attempts < 1:
            raise ValueError("max_attempts must be a positive integer")
        self.gateway = gateway
        self.journal = journal
        self.max_attempts = max_attempts

    async def execute(self, event):
        validate_event(event)
        event_id = event["event_id"]
        if self.journal.was_executed(event_id):
            return {
                "event_id": event_id,
                "status": ALREADY_EXECUTED,
                "attempts": 0,
            }

        last_result = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                result = await self.gateway.send(event)
                if not isinstance(result, dict):
                    raise ValueError("gateway result must be a dict")
                status = result.get("status")
                if status not in GATEWAY_ALL_STATUSES:
                    raise ValueError("gateway result has unsupported status")
                last_result = dict(result)
            except Exception as exc:
                last_result = {"status": "error", "error": str(exc)}

            if last_result["status"] in EXECUTION_SUCCESS_STATUSES:
                outcome = {
                    "event_id": event_id,
                    "status": EXECUTED,
                    "attempts": attempt,
                    "gateway_result": last_result,
                }
                try:
                    self.journal.record(event, outcome)
                except Exception as exc:
                    return {
                        "event_id": event_id,
                        "status": ACK_UNJOURNALED,
                        "attempts": attempt,
                        "gateway_result": last_result,
                        "journal_error": str(exc),
                    }
                return outcome

        return {
            "event_id": event_id,
            "status": FAILED,
            "attempts": self.max_attempts,
            "gateway_result": last_result,
        }

    async def execute_many(self, events):
        # A plain loop: MicroPython's compiler rejects await inside a
        # comprehension.
        outcomes = []
        for event in events:
            outcomes.append(await self.execute(event))
        return outcomes
