"""Business models and validation rules.

Entities are plain JSON dicts checked by a ``validate_*`` function -- there is
no model class per entity type. There used to be (Action, Schedule, Zone,
Endpoint, Group), and nothing outside their own tests ever constructed one:
every path in the product, HTTP and serial and panel alike, passes dicts and
validates them here. Two ways to represent a zone is one too many, so the
unused half went.

``Event`` is the exception and is genuinely used -- the planner builds events
rather than receiving them, so it wants a constructor that validates.
"""

from .actions import ActionValidationError, validate_action
from .devices import (
    DeviceValidationError,
    validate_endpoint,
    validate_group,
    validate_zone,
)
from .events import Event, EventValidationError, validate_event
from .schedules import ScheduleValidationError, validate_schedule

__all__ = [
    "ActionValidationError",
    "DeviceValidationError",
    "Event",
    "EventValidationError",
    "ScheduleValidationError",
    "validate_action",
    "validate_endpoint",
    "validate_event",
    "validate_group",
    "validate_schedule",
    "validate_zone",
]
