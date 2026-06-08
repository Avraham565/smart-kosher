"""Validated loader for packaged city profiles."""

try:
    import ujson as json
except ImportError:
    import json

from ..domain._values import clone_json, is_integer, require_non_empty_string

_cache = None


class CityDataError(ValueError):
    pass


def _data_path():
    normalized = __file__.replace("\\", "/")
    return normalized.rsplit("/", 1)[0] + "/cities.json"


def _validate_number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("{} must be a number".format(field))


def _validate_city(city_id, city):
    if not isinstance(city, dict):
        raise ValueError("{} must be a dict".format(city_id))
    require_non_empty_string(city_id, "city id")
    require_non_empty_string(city.get("name_he"), "{} name_he".format(city_id))

    for field in ("lat", "lon", "elevation"):
        _validate_number(city.get(field), "{} {}".format(city_id, field))
    if not -90 <= city["lat"] <= 90:
        raise ValueError("{} latitude must be in -90..90".format(city_id))
    if not -180 <= city["lon"] <= 180:
        raise ValueError("{} longitude must be in -180..180".format(city_id))
    if city["elevation"] < 0:
        raise ValueError("{} elevation must be non-negative".format(city_id))

    for field in ("candle_offset", "tzais_offset"):
        value = city.get(field)
        if not is_integer(value) or not 0 <= value <= 1440:
            raise ValueError("{} {} must be an integer in 0..1440".format(city_id, field))
    clone_json(city)


def _load_and_validate():
    try:
        with open(_data_path()) as handle:
            cities = json.load(handle)
        if not isinstance(cities, dict) or not cities:
            raise ValueError("cities data must be a non-empty dict")
        for city_id, city in cities.items():
            _validate_city(city_id, city)
        return cities
    except (OSError, ValueError) as exc:
        raise CityDataError("cannot load cities data: {}".format(exc))


def load_cities():
    """Return all packaged city profiles as a defensive copy."""
    global _cache
    if _cache is None:
        _cache = _load_and_validate()
    return clone_json(_cache)


def get_city(city_id):
    """Return one city profile or raise ``KeyError`` for an unknown ID."""
    require_non_empty_string(city_id, "city id")
    city = load_cities().get(city_id)
    if city is None:
        raise KeyError("unknown city: {}".format(city_id))
    return city
