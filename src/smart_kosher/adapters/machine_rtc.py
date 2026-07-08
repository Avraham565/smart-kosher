"""Device RTC behind the SettableClock port (MicroPython ``machine.RTC``)."""

import time

from ..ports.clock import SettableClock

try:
    import machine
    _HAS_MACHINE = True
except ImportError:
    _HAS_MACHINE = False


def has_rtc():
    return _HAS_MACHINE


class MachineRtcClock(SettableClock):
    def now_utc(self):
        now = time.gmtime()
        return (now[0], now[1], now[2], now[3], now[4])

    def set_utc(self, year, month, day, hour, minute, second):
        # machine.RTC.datetime tuple: (year, month, day, weekday, hour,
        # minute, second, subsecond); the port sets weekday to 0 — the RTC
        # derives it from the date.
        machine.RTC().datetime((year, month, day, 0, hour, minute, second, 0))
