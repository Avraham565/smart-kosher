"""Read-only view services — zmanim, Hebrew date, and upcoming events.

Transport-agnostic: every channel (HTTP routes, USB serial, future MQTT)
builds its responses from here. Everything is a pure computation over the
repository and the runtime settings; nothing executes commands or mutates
storage.
"""

import time

from ..zmanim import (
    CANDLE_OFFSET_MINUTES,
    add_gregorian_days,
    compute_zmanim,
    date_info,
    israel_utc_offset_for_local,
    parasha,
)
from .planner import Planner, PlannerConfig

# The fallback used whenever a settings key is missing, and the base every
# composition root builds its own defaults from (each only adds ``city``).
# Public on purpose: product A, product B and the dev server each used to keep
# a private copy of this dict, and they had drifted apart on candle_offset.
#
# ``elevation`` sits here beside lat/lon because the three together are the
# geography a zman is computed from, and the client lets a user type coordinates
# by hand rather than only picking a packaged city. Deriving it from ``city``
# instead would leave every hand-entered location at sea level -- which is the
# bug this replaces: cities.json carried elevations that no caller ever passed,
# so Jerusalem's sunset was computed almost five minutes early for years.
#
# candle_offset is deliberately absent. It is a fixed product rule
# (zmanim.CANDLE_OFFSET_MINUTES), not a setting, and leaving it here would let a
# settings.json written before that decision keep overriding it forever -- a
# stored value always beats a default.
SETTINGS_DEFAULTS = {
    "lat": 31.7683,
    "lon": 35.2137,
    "elevation": 779,
    "utc_offset_minutes": 120,
    "in_israel": True,
}


def _setting(settings, key):
    value = settings.get(key)
    return SETTINGS_DEFAULTS[key] if value is None else value


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
        # fixed offset so clients keep working instead of erroring, and let
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
    # The two Shabbat offsets come from the constants, never from settings: a
    # stale stored value must not be able to move Shabbat.
    return PlannerConfig(
        lat=_setting(settings, "lat"),
        lon=_setting(settings, "lon"),
        altitude=_setting(settings, "elevation"),
        candle_offset=CANDLE_OFFSET_MINUTES,
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


def _format_minutes(total):
    total = int(total) % 1440
    return "{:02d}:{:02d}".format(total // 60, total % 60)


def _build_today_view(settings, year, month, day):
    offset = offset_for_date(settings, year, month, day)
    in_israel = bool(_setting(settings, "in_israel"))
    zmanim = compute_zmanim(
        year, month, day,
        _setting(settings, "lat"), _setting(settings, "lon"),
        _setting(settings, "elevation"),
        CANDLE_OFFSET_MINUTES,
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


class ViewService:
    """Per-hub view facade holding the caches that matter across requests.

    Built once at the composition root and shared by every transport, so
    the planner's per-day zmanim cache and the memoized day view are not
    duplicated per channel.
    """

    def __init__(self, repository=None, clock=None):
        # Public: channels/ops check it to tell whether repository-backed
        # views (upcoming_events) are available.
        self.repository = repository
        # Injectable UTC source (a ports.clock.Clock); defaults to the
        # system/RTC clock. Tests inject a fake to pin "now".
        self._clock = clock
        # PlannerConfig runs a full sanity zmanim computation on construction
        # (~420 trig calls — heavy on the ESP32's software floats), and
        # Planner keeps a per-day zmanim cache that is valuable across
        # requests. Reuse one instance until the settings change.
        self._planner = None
        self._planner_key = None
        # Zmanim for a given date and settings never change, and computing
        # them is the most allocation-heavy view — memoize the last computed
        # day so repeat requests are nearly free.
        self._today_key = None
        self._today_view = None

    def _planner_for(self, settings):
        key = settings_key(settings)
        if self._planner is None or self._planner_key != key:
            self._planner = Planner(planner_config(settings), self.repository)
            self._planner_key = key
        return self._planner

    def _now_utc(self):
        return now_utc() if self._clock is None else self._clock.now_utc()

    def local_today(self, settings):
        """Today's Gregorian date in the hub's configured local time."""
        now = self._now_utc()
        offset = offset_for_date(settings, now[0], now[1], now[2])
        total = now[3] * 60 + now[4] + offset
        if total >= 1440:
            return add_gregorian_days(now[0], now[1], now[2], 1)
        if total < 0:
            return add_gregorian_days(now[0], now[1], now[2], -1)
        return now[0], now[1], now[2]

    def today_view(self, settings, year, month, day):
        """Zmanim, Hebrew date, and day flags for one Gregorian date."""
        key = (year, month, day, settings_key(settings))
        if self._today_key != key:
            self._today_view = _build_today_view(settings, year, month, day)
            self._today_key = key
        return self._today_view

    def upcoming_events(self, settings, days):
        """Planned events from now through ``days`` ahead, with local times.

        Returns ``(events, planner_errors)``. Each event carries
        ``local_date`` ("YYYY-MM-DD") and ``local_time`` ("HH:MM") for
        direct display.
        """
        start = self._now_utc()
        planner = self._planner_for(settings)

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
