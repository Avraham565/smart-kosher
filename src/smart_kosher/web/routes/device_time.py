"""Route for /api/time — set the device RTC (offline product, no NTP).

The hub has no internet, so the only trustworthy time source is the phone
or PC of the person standing next to it. The UI sends the browser's local
time; under MicroPython this writes the RTC, under CPython it returns 501.
"""

import time

from ...domain._values import is_integer
from ...zmanim import gregorian_day_number
from ..responses import ok, err
from . import require_json_body

try:
    import machine
    _HAS_MACHINE = True
except ImportError:
    _HAS_MACHINE = False

_FIELDS = ("year", "month", "day", "hour", "minute", "second")
_RANGES = {"hour": (0, 23), "minute": (0, 59), "second": (0, 59),
           "year": (2013, 2099)}


def register(app):

    @app.post("/api/time")
    async def set_time(req):
        body, error = require_json_body(req)
        if error:
            return error
        for field in _FIELDS:
            if not is_integer(body.get(field)):
                return err("{} must be an integer".format(field))
        for field, (low, high) in _RANGES.items():
            if not low <= body[field] <= high:
                return err("{} must be in {}..{}".format(field, low, high))
        try:
            gregorian_day_number(body["year"], body["month"], body["day"])
        except ValueError as exc:
            return err(str(exc))

        if not _HAS_MACHINE:
            return err("setting the clock is not supported on this platform", 501)

        machine.RTC().datetime((
            body["year"], body["month"], body["day"], 0,
            body["hour"], body["minute"], body["second"], 0,
        ))
        now = time.localtime()
        return ok({"device_time": "{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}".format(
            now[0], now[1], now[2], now[3], now[4], now[5]
        )})
