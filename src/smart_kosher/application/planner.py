"""Deterministic, hardware-independent event planning."""

from ..zmanim import (
    add_gregorian_days,
    compute_zmanim,
    date_info,
    gregorian_day_number,
)

from ..domain._values import is_integer
from ..domain.events import Event
from ..domain.schedules import validate_schedule


class PlannerConfig:
    def __init__(
        self,
        lat,
        lon,
        altitude=0,
        candle_offset=18,
        tzais_offset=40,
        in_israel=True,
        utc_offset_minutes=120,
        utc_offset_for_local=None,
    ):
        self.lat = lat
        self.lon = lon
        self.altitude = altitude
        self.candle_offset = candle_offset
        self.tzais_offset = tzais_offset
        self.in_israel = in_israel
        if not is_integer(utc_offset_minutes):
            raise ValueError("utc_offset_minutes must be an integer")
        self.utc_offset_minutes = utc_offset_minutes
        self.utc_offset_for_local = utc_offset_for_local

        compute_zmanim(2026, 1, 1, lat, lon, altitude, candle_offset, tzais_offset)
        self.offset_for_local(2026, 1, 1, 0, 0)

    def offset_for_local(self, year, month, day, hour, minute):
        if self.utc_offset_for_local is None:
            offset = self.utc_offset_minutes
        else:
            offset = self.utc_offset_for_local(year, month, day, hour, minute)
        if not is_integer(offset) or not -840 <= offset <= 840:
            raise ValueError("UTC offset must be an integer in -840..840 minutes")
        return offset


class Planner:
    def __init__(self, config, repository):
        self.cfg = config
        self.repository = repository
        self.last_errors = []
        self._day_cache = {}
        self._schedules = None
        self._schedule_revision = None

    def _day_data(self, source_date):
        if source_date not in self._day_cache:
            year, month, day = source_date
            self._day_cache[source_date] = (
                compute_zmanim(
                    year, month, day,
                    self.cfg.lat, self.cfg.lon,
                    self.cfg.altitude, self.cfg.candle_offset, self.cfg.tzais_offset,
                ),
                date_info(year, month, day, self.cfg.in_israel),
            )
            if len(self._day_cache) > 9:
                del self._day_cache[min(self._day_cache)]
        return self._day_cache[source_date]

    def _get_schedules(self):
        get_revision = getattr(self.repository, "get_revision", None)
        if get_revision is None:
            return self.repository.get_all("schedules")

        revision = get_revision("schedules")
        if self._schedules is None or revision != self._schedule_revision:
            self._schedules = self.repository.get_all("schedules")
            self._schedule_revision = revision
        return self._schedules

    @staticmethod
    def _matches_recurrence(schedule, source_date, info):
        recurrence_type = schedule["recurrence_type"]
        data = schedule.get("recurrence_data", {})
        dow = info["dow"]

        if recurrence_type == "daily":
            return True
        if recurrence_type == "days_of_week":
            return (dow - 2) % 7 in data["days"]
        if recurrence_type == "assur_bemelacha":
            return info["is_assur_bemelacha"]
        if recurrence_type == "erev_assur_bemelacha":
            return dow == 6 or info["is_erev_yom_tov"]
        if recurrence_type == "motzei_assur_bemelacha":
            return info["is_motzei_assur_bemelacha"]
        if recurrence_type == "chol_hamoed":
            return info["is_chol_hamoed"]
        if recurrence_type == "rosh_chodesh":
            return info["is_rosh_chodesh"]
        if recurrence_type == "hebrew_day_of_month":
            return info["j_day"] == data["day"]
        if recurrence_type == "hebrew_date":
            return info["j_month"] == data["month"] and info["j_day"] == data["day"]
        if recurrence_type == "gregorian_date":
            return source_date[1] == data["month"] and source_date[2] == data["day"]
        if recurrence_type == "one_time":
            return source_date == (data["y"], data["m"], data["d"])
        return False

    def _build_event(self, schedule, source_date, start_minute=None, end_minute=None):
        zmanim, info = self._day_data(source_date)
        if not self._matches_recurrence(schedule, source_date, info):
            return None

        year, month, day = source_date
        source_day_minute = gregorian_day_number(year, month, day) * 1440
        trigger_type = schedule["trigger_type"]
        trigger_data = schedule.get("trigger_data", {})

        if trigger_type == "fixed_time":
            hour = trigger_data["h"]
            minute = trigger_data["m"]
            utc_minute = (
                source_day_minute
                + hour * 60
                + minute
                - self.cfg.offset_for_local(year, month, day, hour, minute)
            )
        else:
            value = zmanim.get(trigger_data["zman"])
            if value is None:
                return None
            if trigger_type == "zman_offset":
                value += trigger_data.get("offset", 0)
            utc_minute = source_day_minute + int(value // 1)

        if start_minute is not None and utc_minute <= start_minute:
            return None
        if end_minute is not None and utc_minute > end_minute:
            return None

        return Event(
            event_id="{}:{}:{}:{}:{}".format(
                schedule["id"], year, month, day, utc_minute
            ),
            schedule_id=schedule["id"],
            source_date=source_date,
            utc_minute=utc_minute,
            target_type=schedule["target_type"],
            target_id=schedule["target_id"],
            action_type=schedule["action_type"],
            action_data=schedule.get("action_data", {}),
        ).to_dict()

    @staticmethod
    def utc_minute(timestamp):
        if not isinstance(timestamp, tuple) or len(timestamp) != 5:
            raise ValueError("UTC timestamp must be (year, month, day, hour, minute)")
        year, month, day, hour, minute = timestamp
        day_number = gregorian_day_number(year, month, day)
        if not is_integer(hour) or not 0 <= hour <= 23:
            raise ValueError("hour must be in 0..23")
        if not is_integer(minute) or not 0 <= minute <= 59:
            raise ValueError("minute must be in 0..59")
        return day_number * 1440 + hour * 60 + minute

    def events_between(self, start_exclusive, end_inclusive, max_window_minutes=2880):
        """Return events in ``(start_exclusive, end_inclusive]``."""
        start_minute = self.utc_minute(start_exclusive)
        end_minute = self.utc_minute(end_inclusive)
        if end_minute < start_minute:
            raise ValueError("end timestamp must not precede start timestamp")
        if end_minute - start_minute > max_window_minutes:
            raise ValueError("catch-up window is larger than max_window_minutes")

        first_day = max(1, gregorian_day_number(*start_exclusive[:3]) - 3)
        last_day = gregorian_day_number(*end_inclusive[:3]) + 3

        self.last_errors = []
        events = {}
        for schedule in self._get_schedules():
            try:
                validate_schedule(schedule)
                if not schedule.get("enabled", True):
                    continue
            except (KeyError, TypeError, ValueError) as exc:
                self.last_errors.append({
                    "schedule_id": schedule.get("id") if isinstance(schedule, dict) else None,
                    "error": str(exc),
                })
                continue

            for day_number in range(first_day, last_day + 1):
                source_date = None
                try:
                    source_date = add_gregorian_days(1, 1, 1, day_number - 1)
                    event = self._build_event(
                        schedule,
                        source_date,
                        start_minute=start_minute,
                        end_minute=end_minute,
                    )
                    if event:
                        events[event["event_id"]] = event
                except (KeyError, TypeError, ValueError) as exc:
                    self.last_errors.append({
                        "schedule_id": schedule["id"],
                        "source_date": source_date,
                        "error": str(exc),
                    })

        return sorted(events.values(), key=lambda event: (event["utc_minute"], event["event_id"]))

    def due_events(self, year, month, day, hour_utc, minute_utc):
        current = (year, month, day, hour_utc, minute_utc)
        previous_minute = self.utc_minute(current) - 1
        previous_date = add_gregorian_days(1, 1, 1, previous_minute // 1440 - 1)
        previous = (
            previous_date[0], previous_date[1], previous_date[2],
            (previous_minute % 1440) // 60, previous_minute % 60,
        )
        return self.events_between(previous, current, max_window_minutes=1)
