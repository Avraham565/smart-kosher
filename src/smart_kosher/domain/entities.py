"""Repository entity validation shared by persistence adapters."""

from ._values import require_non_empty_string, validate_json
from .devices import validate_endpoint, validate_group, validate_zone
from .events import validate_event
from .schedules import validate_schedule

CONFIG_ENTITY_TYPES = ("zones", "endpoints", "groups", "schedules")
ALL_ENTITY_TYPES = CONFIG_ENTITY_TYPES + ("journal",)


def validate_entity(entity_type, entity):
    if entity_type not in ALL_ENTITY_TYPES:
        raise ValueError("unsupported entity type: {}".format(entity_type))
    if not isinstance(entity, dict):
        raise ValueError("entity must be a dict")
    require_non_empty_string(entity.get("id"), "entity id")
    if entity_type == "zones":
        validate_zone(entity)
    elif entity_type == "endpoints":
        validate_endpoint(entity)
    elif entity_type == "groups":
        validate_group(entity)
    elif entity_type == "schedules":
        validate_schedule(entity)
    else:
        if not isinstance(entity.get("event"), dict):
            raise ValueError("journal record requires event")
        validate_event(entity["event"])
        if not isinstance(entity.get("result"), dict):
            raise ValueError("journal record requires result")
    validate_json(entity)
    return True
