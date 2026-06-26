"""Routes for /api/settings — runtime configuration (city, time)."""

import time

from ..responses import ok, err
from . import require_json_body

_ALLOWED_KEYS = {"city", "lat", "lon", "utc_offset_minutes", "in_israel",
                 "candle_offset", "tzais_offset"}
_NUMERIC_KEYS = {"lat", "lon", "candle_offset", "tzais_offset"}


def _type_error(key, value):
    if key == "city":
        if not isinstance(value, str) or not value.strip():
            return "city must be a non-empty string"
    elif key in _NUMERIC_KEYS:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return "{} must be a number".format(key)
    elif key == "utc_offset_minutes":
        if not isinstance(value, int) or isinstance(value, bool):
            return "utc_offset_minutes must be an integer"
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
            msg = _type_error(key, value)
            if msg:
                return err(msg)
        settings_store.update(body)
        return ok(settings_store.get())
