"""JSON-native schemas for zones, endpoints, and groups."""

from .actions import ACTION_TYPES
from ._values import clone_json, require_non_empty_string, validate_json


class DeviceValidationError(ValueError):
    pass


def _validate_base(entity):
    if not isinstance(entity, dict):
        raise ValueError("entity must be a dict")
    require_non_empty_string(entity.get("id"), "entity id")
    if "name" in entity:
        require_non_empty_string(entity["name"], "name")
    validate_json(entity)


def validate_zone(zone):
    try:
        _validate_base(zone)
    except ValueError as exc:
        raise DeviceValidationError(str(exc))
    return True


def validate_endpoint(endpoint):
    try:
        _validate_base(endpoint)
        for field in ("zone_id", "device_type"):
            if field in endpoint:
                require_non_empty_string(endpoint[field], field)
        if "capabilities" in endpoint:
            capabilities = endpoint["capabilities"]
            if not isinstance(capabilities, list):
                raise ValueError("capabilities must be a list")
            if any(not isinstance(item, str) or item not in ACTION_TYPES for item in capabilities):
                raise ValueError("capabilities contains an unsupported action")
            if len(set(capabilities)) != len(capabilities):
                raise ValueError("capabilities must not contain duplicates")
    except ValueError as exc:
        raise DeviceValidationError(str(exc))
    return True


def validate_group(group):
    try:
        _validate_base(group)
        if "member_ids" in group:
            members = group["member_ids"]
            if not isinstance(members, list):
                raise ValueError("member_ids must be a list")
            for member_id in members:
                require_non_empty_string(member_id, "member id")
            if len(set(members)) != len(members):
                raise ValueError("member_ids must not contain duplicates")
    except ValueError as exc:
        raise DeviceValidationError(str(exc))
    return True


class _DeviceModel:
    validator = None

    def __init__(self, value):
        self.validator(value)
        self._value = clone_json(value)

    @property
    def id(self):
        return self._value["id"]

    def to_dict(self):
        return clone_json(self._value)


class Zone(_DeviceModel):
    validator = staticmethod(validate_zone)


class Endpoint(_DeviceModel):
    validator = staticmethod(validate_endpoint)


class Group(_DeviceModel):
    validator = staticmethod(validate_group)
