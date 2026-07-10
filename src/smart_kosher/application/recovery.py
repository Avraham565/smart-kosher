"""Recovery orchestration after a delayed loop or restart."""

from ..domain._values import is_integer


class RecoveryService:
    def __init__(self, planner, executor, max_catch_up_minutes=2880):
        if not is_integer(max_catch_up_minutes) or max_catch_up_minutes < 1:
            raise ValueError("max_catch_up_minutes must be a positive integer")
        self.planner = planner
        self.executor = executor
        self.max_catch_up_minutes = max_catch_up_minutes

    async def recover(self, last_seen_exclusive, now_inclusive):
        events = self.planner.events_between(
            last_seen_exclusive,
            now_inclusive,
            max_window_minutes=self.max_catch_up_minutes,
        )
        outcomes = await self.executor.execute_many(events)
        return {
            "event_count": len(events),
            "events": events,
            "outcomes": outcomes,
        }
