"""Validated loader for packaged city profiles."""

try:
    import ujson as json
except ImportError:
    import json

from ..domain._values import clone_json, require_non_empty_string

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
    # Non-negative is the upstream contract, not our preference: KosherJava's
    # GeoLocation.setElevation rejects negative values outright, and the zenith
    # correction acos(R/(R+h)) is undefined below sea level. Tiberias sits at
    # roughly -110 m and is therefore stored as 0, which is what the reference
    # implementation would compute for it anyway.
    if city["elevation"] < 0:
        raise ValueError("{} elevation must be non-negative".format(city_id))

    # Elevations are the SRTM 30 m digital elevation model sampled at this
    # city's own lat/lon -- not a published "elevation of city X", which is a
    # figure without a single answer (Jerusalem spans ~650-830 m). Sampling the
    # exact coordinate we compute zmanim for is the only self-consistent
    # choice. Cross-checked against ASTER 30 m; the two models agree to within
    # 10 m everywhere. Re-sample from the same source if a coordinate moves.
    #
    # A city is geography and nothing else: name, latitude, longitude,
    # elevation. Both Shabbat offsets used to live here too, per city, and
    # nothing ever read either of them -- so those numbers disagreed with what
    # the system actually computed for years without any visible symptom. They
    # are now fixed product rules and must not come back as city data.
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


def search_cities(query, limit=None):
    """Cities whose name starts with ``query``, or any of whose words does.

    Word prefixes, not a plain prefix: the panel's search is typed one Hebrew
    letter at a time on a touchscreen, and somebody looking for בני ברק is as
    likely to start with ברק. Two letters narrow forty cities to a handful,
    which is the whole reason the picker can be a search box instead of a list
    the RGB panel is not allowed to scroll.

    An empty query returns everything, so a caller can render the full list
    before a key is pressed. Results are ordered by name, and entries whose
    first word matches come first -- typing בני should not put בני ברק below
    a city that merely contains the word.

    Returns a list of ``{"id": ..., "name_he": ..., "lat": ..., ...}``.
    """
    entries = []
    for city_id, city in load_cities().items():
        entry = {"id": city_id}
        entry.update(city)
        entries.append(entry)
    entries.sort(key=lambda c: c["name_he"])

    if not isinstance(query, str):
        query = ""
    query = query.strip()
    if query:
        leading, trailing = [], []
        for entry in entries:
            words = entry["name_he"].split()
            if entry["name_he"].startswith(query):
                leading.append(entry)
            elif any(word.startswith(query) for word in words):
                trailing.append(entry)
        entries = leading + trailing

    if limit is not None:
        entries = entries[:limit]
    return entries


def resolve_city(name):
    """Find a packaged city by its ID or its Hebrew name. ``None`` if neither.

    Two spellings exist in the wild for the same thing: the client picker sends
    an ID ("jerusalem"), while a settings file written before the picker holds
    the Hebrew name ("ירושלים"). Both must land on the same profile, or picking
    your city from the list would behave differently than having it already.

    Returns ``(city_id, city)`` so the caller can store either form.
    """
    if not isinstance(name, str):
        return None
    name = name.strip()
    if not name:
        return None
    cities = load_cities()
    city = cities.get(name)
    if city is not None:
        return name, city
    for city_id, candidate in cities.items():
        if candidate["name_he"] == name:
            return city_id, candidate
    return None
