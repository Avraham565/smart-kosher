"""Offline Israeli civil-time rules.

The current statutory rule, used from 2013 onward:
- DST starts at 02:00 on the Friday before the last Sunday in March.
- DST ends at 02:00 on the last Sunday in October.

For the repeated hour when DST ends, a fixed local schedule is resolved to the
first occurrence (daylight time).
"""

from .hebrew_cal import add_gregorian_days, day_of_week


def _last_sunday(year, month, last_day):
    dow = day_of_week(year, month, last_day)  # 1=Sunday
    return last_day - (dow - 1)


def israel_dst_dates(year):
    if not isinstance(year, int) or year < 2013:
        raise ValueError("Israeli DST rules are supported from 2013 onward")
    last_sunday_march = _last_sunday(year, 3, 31)
    start = add_gregorian_days(year, 3, last_sunday_march, -2)
    end = (year, 10, _last_sunday(year, 10, 31))
    return start, end


def israel_utc_offset_for_local(year, month, day, hour, minute):
    """Return the Israeli UTC offset, in minutes, for a local civil time."""
    if not isinstance(hour, int) or not 0 <= hour <= 23:
        raise ValueError("hour must be in 0..23")
    if not isinstance(minute, int) or not 0 <= minute <= 59:
        raise ValueError("minute must be in 0..59")

    current = (year, month, day)
    start, end = israel_dst_dates(year)
    if current < start or current > end:
        return 120
    if start < current < end:
        return 180
    if current == start:
        if hour == 2:
            raise ValueError("local times from 02:00 through 02:59 do not exist at DST start")
        return 180 if hour >= 3 else 120
    # The repeated hour on the end date resolves to its first occurrence.
    return 180 if (hour, minute) < (2, 0) else 120
