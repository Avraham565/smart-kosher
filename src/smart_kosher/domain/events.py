"""Events produced by the planner and consumed by an executor."""

from ..zmanim import gregorian_day_number
from ._values import clone_json, is_integer, require_non_empty_string, validate_json
from .actions import validate_action


class EventValidationError(ValueError):
    pass


def validate_event(event):
    try:
        if not isinstance(event, dict):
            raise ValueError("event must be a dict")
        for field in ("event_id", "schedule_id", "target_type", "target_id"):
            require_non_empty_string(event.get(field), field)
        source_date = event.get("source_date")
        if not isinstance(source_date, (tuple, list)) or len(source_date) != 3:
            raise ValueError("source_date must contain year, month, and day")
        if any(not is_integer(value) for value in source_date):
            raise ValueError("source_date values must be integers")
        gregorian_day_number(*source_date)
        if not is_integer(event.get("utc_minute")) or event["utc_minute"] < 0:
            raise ValueError("utc_minute must be a non-negative integer")
        validate_action(event.get("action_type"), event.get("action_data", {}))
        validate_json(event)
    except ValueError as exc:
        raise EventValidationError(str(exc))
    return True


class Event:
    def __init__(
        self,
        event_id,
        schedule_id,
        source_date,
        utc_minute,
        target_type,
        target_id,
        action_type,
        action_data=None,
    ):
        value = {
            "event_id": event_id,
            "schedule_id": schedule_id,
            "source_date": tuple(source_date),
            "utc_minute": utc_minute,
            "target_type": target_type,
            "target_id": target_id,
            "action_type": action_type,
            "action_data": {} if action_data is None else action_data,
        }
        validate_event(value)
        self._value = clone_json(value)

    def to_dict(self):
        return clone_json(self._value)
