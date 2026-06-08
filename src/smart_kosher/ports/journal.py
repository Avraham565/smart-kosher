"""Execution journal used for persistent idempotency."""


class EventJournal:
    def was_executed(self, event_id):
        raise NotImplementedError

    def record(self, event, result):
        raise NotImplementedError

    def get(self, event_id):
        raise NotImplementedError
