"""Bridges runtime settings to the planner and zmanim core for the Web API.

Everything here is read-only: it computes views (today's zmanim, upcoming
schedule events) and never executes commands or mutates storage.
"""

import time

from ..application.planner import Planner, PlannerConfig
from ..zmanim import (
    add_gregorian_days,
    compute_zmanim,
    date_info,
    israel_utc_offset_for_local,
    parasha,
)

_SETTINGS_DEFAULTS = {
    "lat": 31.7683,
    "lon": 35.2137,
    "utc_offset_minutes": 120,
    "candle_offset": 18,
    "tzais_offset": 40,
    "in_israel": True,
}


def _setting(settings, key):
    value = settings.get(key)
    return _SETTINGS_DEFAULTS[key] if value is None else value


def offset_resolver(settings):
    """Return a callable resolving a local civil time to a UTC offset."""
    fixed = int(_setting(settings, "utc_offset_minutes"))

    if not _setting(settings, "in_israel"):
        def fixed_offset(year, month, day, hour, minute):
            return fixed
        return fixed_offset

    def israel_offset(year, month, day, hour, minute):
        # Israeli DST rules are defined from 2013 onward. Earlier years mean
        # an unset device RTC (fresh boot reads 2000-01-01): fall back to the
        # fixed offset so the UI keeps working instead of erroring, and let
        # the status route flag the unset clock.
        if year < 2013:
            return fixed
        return israel_utc_offset_for_local(year, month, day, hour, minute)

    return israel_offset


def offset_for_date(settings, year, month, day):
    """UTC offset used for displaying times on a given date.

    Noon is safely outside both Israeli DST transition windows (02:00).
    """
    return offset_resolver(settings)(year, month, day, 12, 0)


def planner_config(settings):
    return PlannerConfig(
        lat=_setting(settings, "lat"),
        lon=_setting(settings, "lon"),
        candle_offset=int(_setting(settings, "candle_offset")),
        tzais_offset=int(_setting(settings, "tzais_offset")),
        in_israel=bool(_setting(settings, "in_israel")),
        utc_offset_minutes=int(_setting(settings, "utc_offset_minutes")),
        utc_offset_for_local=offset_resolver(settings),
    )


def now_utc():
    now = time.gmtime()
    return (now[0], now[1], now[2], now[3], now[4])


def settings_key(settings):
    """Hashable snapshot of the settings that affect planning."""
    return tuple(sorted(
        (key, value) for key, value in settings.items() if key != "device_time"
    ))


# PlannerConfig runs a full sanity zmanim computation on construction
# (~420 trig calls — heavy on the ESP32's software floats), and Planner
# keeps a per-day zmanim cache that is valuable across requests. Reuse
# one instance until the settings or repository change.
_planner_cache = {"key": None, "repo_id": None, "planner": None}


def _planner_for(repository, settings):
    key = settings_key(settings)
    if (_planner_cache["key"] != key
            or _planner_cache["repo_id"] != id(repository)):
        _planner_cache["planner"] = Planner(planner_config(settings), repository)
        _planner_cache["key"] = key
        _planner_cache["repo_id"] = id(repository)
    return _planner_cache["planner"]


def _format_minutes(total):
    total = int(total) % 1440
    return "{:02d}:{:02d}".format(total // 60, total % 60)


def today_view(settings, year, month, day):
    """Zmanim, Hebrew date, and day flags for one Gregorian date."""
    offset = offset_for_date(settings, year, month, day)
    in_israel = bool(_setting(settings, "in_israel"))
    zmanim = compute_zmanim(
        year, month, day,
        _setting(settings, "lat"), _setting(settings, "lon"),
        0,
        int(_setting(settings, "candle_offset")),
        int(_setting(settings, "tzais_offset")),
    )
    info = date_info(year, month, day, in_israel)

    local_zmanim = {}
    for key, value in zmanim.items():
        local_zmanim[key] = None if value is None else _format_minutes(value + offset)

    return {
        "date": "{:04d}-{:02d}-{:02d}".format(year, month, day),
        "hebrew_date": {
            "year": info["j_year"],
            "month": info["j_month"],
            "day": info["j_day"],
        },
        "day_of_week": info["dow"],
        "parasha": parasha(year, month, day, in_israel),
        "significant_day": info["significant_day"],
        "is_shabbat": info["is_shabbat"],
        "is_yom_tov": info["is_yom_tov"],
        "is_erev_yom_tov": info["is_erev_yom_tov"],
        "is_assur_bemelacha": info["is_assur_bemelacha"],
        "is_chol_hamoed": info["is_chol_hamoed"],
        "is_rosh_chodesh": info["is_rosh_chodesh"],
        "is_taanis": info["is_taanis"],
        "day_of_omer": info["day_of_omer"],
        "utc_offset_minutes": offset,
        "zmanim": local_zmanim,
    }


def upcoming_events(repository, settings, days):
    """Planned events from now through ``days`` ahead, with local times.

    Returns ``(events, planner_errors)``. Each event carries ``local_date``
    ("YYYY-MM-DD") and ``local_time`` ("HH:MM") for direct display.
    """
    start = now_utc()
    planner = _planner_for(repository, settings)

    end_date = add_gregorian_days(start[0], start[1], start[2], days)
    end = (end_date[0], end_date[1], end_date[2], start[3], start[4])

    events = planner.events_between(start, end, max_window_minutes=days * 1440)

    start_minute = planner.utc_minute(start)
    view = []
    for event in events:
        offset = offset_for_date(settings, *event["source_date"])
        local_minute = event["utc_minute"] + offset
        local_day = local_minute // 1440
        local_date = add_gregorian_days(1, 1, 1, local_day - 1)
        view.append({
            "event_id": event["event_id"],
            "schedule_id": event["schedule_id"],
            "target_type": event["target_type"],
            "target_id": event["target_id"],
            "action_type": event["action_type"],
            "in_minutes": event["utc_minute"] - start_minute,
            "local_date": "{:04d}-{:02d}-{:02d}".format(*local_date),
            "local_time": _format_minutes(local_minute),
        })
    return view, list(planner.last_errors)
