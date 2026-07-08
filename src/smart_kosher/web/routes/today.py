"""Route for /api/today — Hebrew date, day flags, and zmanim in local time."""

import time

from .. import planning
from ..responses import ok, err
from ...zmanim import add_gregorian_days


def _parse_date(raw):
    parts = raw.split("-")
    if len(parts) != 3:
        raise ValueError("date must be YYYY-MM-DD")
    return int(parts[0]), int(parts[1]), int(parts[2])


def _local_today(settings):
    now = time.gmtime()
    offset = planning.offset_for_date(settings, now[0], now[1], now[2])
    total = now[3] * 60 + now[4] + offset
    if total >= 1440:
        return add_gregorian_days(now[0], now[1], now[2], 1)
    if total < 0:
        return add_gregorian_days(now[0], now[1], now[2], -1)
    return now[0], now[1], now[2]


def _settings_key(settings):
    return tuple(sorted(
        (key, value) for key, value in settings.items() if key != "device_time"
    ))


def register(app, settings_store):
    # Zmanim for a given date and settings never change, and computing them
    # is the most allocation-heavy request the hub serves — memoize the last
    # computed day so repeat visits to the tab are nearly free.
    cache = {"key": None, "view": None}

    @app.get("/api/today")
    async def get_today(req):
        raw = req.args.get("date")
        try:
            settings = settings_store.get()
            if raw:
                year, month, day = _parse_date(raw)
            else:
                year, month, day = _local_today(settings)
            key = (year, month, day, _settings_key(settings))
            if cache["key"] != key:
                cache["view"] = planning.today_view(settings, year, month, day)
                cache["key"] = key
            return ok(cache["view"])
        except (KeyError, TypeError, ValueError) as exc:
            return err(str(exc))
