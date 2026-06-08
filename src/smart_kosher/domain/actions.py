"""Device-independent actions."""

from ._values import clone_json, is_integer, optional_dict, require_non_empty_string, validate_json

ACTION_TYPES = ("on", "off", "toggle", "set_level", "dim")


class ActionValidationError(ValueError):
    pass


def validate_action(action_type, action_data=None):
    try:
        require_non_empty_string(action_type, "action_type")
        if action_type not in ACTION_TYPES:
            raise ValueError("unsupported action_type: {}".format(action_type))
        data = optional_dict(action_data, "action_data")
        validate_json(data)
        if action_type in ("set_level", "dim"):
            level = data.get("level")
            if not is_integer(level) or not 0 <= level <= 100: # type: ignore
                raise ValueError("{} requires integer level in 0..100".format(action_type))
    except ValueError as exc:
        raise ActionValidationError(str(exc))
    return True


class Action:
    def __init__(self, action_type, data=None):
        validate_action(action_type, data)
        self.action_type = action_type
        self.data = clone_json(data or {})

    def to_dict(self):
        return {
            "action_type": self.action_type,
            "action_data": clone_json(self.data),
        }
