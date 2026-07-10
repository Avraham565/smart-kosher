"""Idempotent event execution with bounded retries."""

from ..domain._values import is_integer
from ..domain.events import validate_event
from ..ports.device_gateway import EXECUTION_SUCCESS_STATUSES, GATEWAY_ALL_STATUSES


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
                "status": "already_executed",
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
                    "status": "executed",
                    "attempts": attempt,
                    "gateway_result": last_result,
                }
                try:
                    self.journal.record(event, outcome)
                except Exception as exc:
                    return {
                        "event_id": event_id,
                        "status": "ack_unjournaled",
                        "attempts": attempt,
                        "gateway_result": last_result,
                        "journal_error": str(exc),
                    }
                return outcome

        return {
            "event_id": event_id,
            "status": "failed",
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
