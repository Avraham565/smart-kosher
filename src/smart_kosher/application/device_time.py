"""Set the device clock from a trusted client (offline hub, no NTP).

Contract: clients send **UTC**, not local civil time. The RTC holds UTC and
every local time the hub shows is derived from it through the settings' UTC
offset — a client that sends local time here shifts every computed zman.
"""

from ..domain._values import is_integer
from ..zmanim import gregorian_day_number

_FIELDS = ("year", "month", "day", "hour", "minute", "second")
_RANGES = {"hour": (0, 23), "minute": (0, 59), "second": (0, 59),
           "year": (2013, 2099)}


class ClockUnsupportedError(Exception):
    """This platform has no settable RTC."""


class DeviceTimeService:
    def __init__(self, clock=None):
        """``clock`` is a SettableClock, or None when the platform has none."""
        self._clock = clock

    def set_time(self, fields):
        """Validate ``fields`` (UTC) and write them to the RTC.

        Raises ValueError on bad input and ClockUnsupportedError when there
        is no RTC. Returns the time just set, formatted for display.
        """
        for field in _FIELDS:
            if not is_integer(fields.get(field)):
                raise ValueError("{} must be an integer".format(field))
        for field, (low, high) in _RANGES.items():
            if not low <= fields[field] <= high:
                raise ValueError("{} must be in {}..{}".format(field, low, high))
        # Rejects impossible dates such as February 30th.
        gregorian_day_number(fields["year"], fields["month"], fields["day"])

        if self._clock is None:
            raise ClockUnsupportedError(
                "setting the clock is not supported on this platform")

        self._clock.set_utc(*(fields[field] for field in _FIELDS))
        return "{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}".format(
            *(fields[field] for field in _FIELDS))
