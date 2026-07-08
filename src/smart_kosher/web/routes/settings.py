"""Routes for /api/settings — runtime configuration (city, time)."""

import time

from ...data import load_cities
from ..responses import ok, err
from . import require_json_body

_ALLOWED_KEYS = {"city", "lat", "lon", "utc_offset_minutes", "in_israel",
                 "candle_offset", "tzais_offset"}


def _is_number(value):
    return not isinstance(value, bool) and isinstance(value, (int, float))


def _is_int(value):
    return not isinstance(value, bool) and isinstance(value, int)


def _value_error(key, value):
    if key == "city":
        if not isinstance(value, str) or not value.strip():
            return "city must be a non-empty string"
    elif key == "lat":
        if not _is_number(value) or not -90 <= value <= 90:
            return "lat must be a number in -90..90"
    elif key == "lon":
        if not _is_number(value) or not -180 <= value <= 180:
            return "lon must be a number in -180..180"
    elif key == "utc_offset_minutes":
        if not _is_int(value) or not -840 <= value <= 840:
            return "utc_offset_minutes must be an integer in -840..840"
    elif key in ("candle_offset", "tzais_offset"):
        if not _is_int(value) or not 0 <= value <= 1440:
            return "{} must be an integer in 0..1440".format(key)
    elif key == "in_israel":
        if not isinstance(value, bool):
            return "in_israel must be a boolean"
    return None


def register(app, settings_store):

    @app.get("/api/settings")
    async def get_settings(req):
        now = time.localtime()
        data = settings_store.get()
        data["device_time"] = "{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}".format(
            now[0], now[1], now[2], now[3], now[4], now[5]
        )
        return ok(data)

    @app.put("/api/settings")
    async def update_settings(req):
        body, error = require_json_body(req)
        if error:
            return error
        unknown = set(body.keys()) - _ALLOWED_KEYS
        if unknown:
            return err("unknown settings keys: {}".format(", ".join(sorted(unknown))))
        for key, value in body.items():
            msg = _value_error(key, value)
            if msg:
                return err(msg)
        settings_store.update(body)
        return ok(settings_store.get())

    @app.get("/api/settings/cities")
    async def list_cities(req):
        cities = []
        for city_id, city in load_cities().items():
            entry = {"id": city_id}
            entry.update(city)
            cities.append(entry)
        cities.sort(key=lambda c: c["name_he"])
        return ok(cities)
