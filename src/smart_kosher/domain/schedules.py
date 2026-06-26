"""Schedule model and business validation rules."""

from ..zmanim import gregorian_day_number

from .actions import validate_action
from ._values import clone_json, is_integer, require_non_empty_string, validate_json

ZMAN_KEYS = {
    "alot_hashachar", "talit_and_tefillin", "netz_hachama",
    "sof_zman_shema_gra", "sof_zman_shema_mga",
    "sof_zman_tfilla_gra", "sof_zman_tfilla_mga",
    "chatzot_hayom", "mincha_gedola", "mincha_gedola_30min",
    "mincha_ketana", "plag_hamincha", "shkia", "tset_hakohavim",
    "tset_hakohavim_shabbat", "tset_hakohavim_tsom",
    "tset_hakohavim_rabeinu_tam", "chatzot_halayla", "candle_lighting",
}

RECURRENCE_TYPES = {
    "daily", "days_of_week", "assur_bemelacha", "erev_assur_bemelacha",
    "motzei_assur_bemelacha",
    "chol_hamoed", "rosh_chodesh", "hebrew_day_of_month", "hebrew_date",
    "gregorian_date", "one_time",
}
TARGET_TYPES = ("endpoint", "group")


class ScheduleValidationError(ValueError):
    pass


def _dict_field(value, field):
    if field not in value:
        return {}
    field_value = value[field]
    if not isinstance(field_value, dict):
        raise ValueError("{} must be a dict".format(field))
    return field_value


def validate_schedule(schedule):
    try:
        if not isinstance(schedule, dict):
            raise ValueError("schedule must be a dict")

        require_non_empty_string(schedule.get("id"), "schedule id")
        target_type = require_non_empty_string(schedule.get("target_type"), "target_type")
        if target_type not in TARGET_TYPES:
            raise ValueError("unsupported target_type: {}".format(target_type))
        require_non_empty_string(schedule.get("target_id"), "target_id")
        if "enabled" in schedule and not isinstance(schedule["enabled"], bool):
            raise ValueError("enabled must be a boolean")

        action_data = _dict_field(schedule, "action_data")
        validate_action(schedule.get("action_type"), action_data)
        if schedule.get("action_type") == "toggle":
            raise ValueError("toggle is not allowed in schedules; use on or off")

        trigger_type = schedule.get("trigger_type")
        trigger_data = _dict_field(schedule, "trigger_data")
        if trigger_type == "fixed_time":
            hour = trigger_data.get("h")
            minute = trigger_data.get("m")
            if not is_integer(hour) or not 0 <= hour <= 23:
                raise ValueError("fixed_time hour must be in 0..23")
            if not is_integer(minute) or not 0 <= minute <= 59:
                raise ValueError("fixed_time minute must be in 0..59")
        elif trigger_type in ("zman", "zman_offset"):
            zman = trigger_data.get("zman")
            require_non_empty_string(zman, "zman")
            if zman not in ZMAN_KEYS:
                raise ValueError("unknown zman: {}".format(zman))
            if trigger_type == "zman_offset":
                offset = trigger_data.get("offset", 0)
                if not is_integer(offset) or not -2880 <= offset <= 2880:
                    raise ValueError("zman offset must be in -2880..2880 minutes")
        else:
            raise ValueError("unsupported trigger_type")

        recurrence_type = schedule.get("recurrence_type")
        recurrence_data = _dict_field(schedule, "recurrence_data")
        if recurrence_type not in RECURRENCE_TYPES:
            raise ValueError("unsupported recurrence_type")

        if recurrence_type == "days_of_week":
            days = recurrence_data.get("days")
            if not isinstance(days, list) or not days or any(
                not is_integer(day) or day not in range(7) for day in days
            ):
                raise ValueError("days_of_week requires at least one day in 0..6")
            if len(set(days)) != len(days):
                raise ValueError("days_of_week must not contain duplicates")

        required_fields = {
            "hebrew_day_of_month": ("day",),
            "hebrew_date": ("month", "day"),
            "gregorian_date": ("month", "day"),
            "one_time": ("y", "m", "d"),
        }
        for field in required_fields.get(recurrence_type, ()):
            if not is_integer(recurrence_data.get(field)):
                raise ValueError("{} requires integer {}".format(recurrence_type, field))

        if recurrence_type == "hebrew_day_of_month":
            if not 1 <= recurrence_data["day"] <= 30:
                raise ValueError("Hebrew day must be in 1..30")
        if recurrence_type == "hebrew_date":
            if not 1 <= recurrence_data["month"] <= 13 or not 1 <= recurrence_data["day"] <= 30:
                raise ValueError("invalid Hebrew month or day")
        if recurrence_type == "gregorian_date":
            month = recurrence_data["month"]
            day = recurrence_data["day"]
            if not 1 <= month <= 12:
                raise ValueError("invalid Gregorian month or day")
            max_day = (31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)[month - 1]
            if not 1 <= day <= max_day:
                raise ValueError("invalid Gregorian month or day")
        if recurrence_type == "one_time":
            gregorian_day_number(
                recurrence_data["y"], recurrence_data["m"], recurrence_data["d"]
            )
        validate_json(schedule)
    except ValueError as exc:
        raise ScheduleValidationError(str(exc))
    return True


class Schedule:
    def __init__(self, value):
        validate_schedule(value)
        self._value = clone_json(value)

    @property
    def id(self):
        return self._value["id"]

    def to_dict(self):
        return clone_json(self._value)
