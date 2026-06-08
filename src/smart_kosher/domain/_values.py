"""Small JSON-value helpers shared by domain modules."""


def clone_json(value):
    if isinstance(value, dict):
        cloned = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("JSON object keys must be strings")
            cloned[key] = clone_json(item)
        return cloned
    if isinstance(value, list):
        return [clone_json(item) for item in value]
    if isinstance(value, tuple):
        return tuple(clone_json(item) for item in value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise ValueError("value must contain JSON-compatible data")


def validate_json(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("JSON object keys must be strings")
            validate_json(item)
        return True
    if isinstance(value, (list, tuple)):
        for item in value:
            validate_json(item)
        return True
    if value is None or isinstance(value, (str, int, float, bool)):
        return True
    raise ValueError("value must contain JSON-compatible data")


def is_integer(value):
    return isinstance(value, int) and not isinstance(value, bool)


def require_non_empty_string(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("{} must be a non-empty string".format(field))
    return value


def optional_dict(value, field):
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("{} must be a dict".format(field))
    return value
