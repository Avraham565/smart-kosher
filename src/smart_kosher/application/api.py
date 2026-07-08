"""Transport-agnostic command surface — the single API every channel speaks.

Each channel (HTTP routes, USB serial, future MQTT) translates its own
envelope into ``Api.dispatch(op, params)`` and renders ``ApiError.kind``
back into its own status vocabulary. Business rules stay in the services;
this module only routes ops, validates parameter shape, and classifies
errors.
"""

import gc
import time

from ..data import load_cities
from ..domain.devices import DeviceValidationError
from ..domain.schedules import ScheduleValidationError
from .crud_service import InUseError, NotFoundError
from .device_time import ClockUnsupportedError

APP_VERSION = "0.1.0"

_CRUD_ENTITIES = ("zones", "endpoints", "groups", "schedules")
_MAX_PREVIEW_DAYS = 7

# Error kinds — each transport maps these to its own status codes
# (HTTP: 400/404/409/501/500).
BAD_REQUEST = "bad_request"
NOT_FOUND = "not_found"
CONFLICT = "conflict"
UNSUPPORTED = "unsupported"
INTERNAL = "internal"


class ApiError(Exception):
    def __init__(self, kind, message):
        super().__init__(message)
        self.kind = kind


def _require_id(params):
    entity_id = params.get("id")
    if not isinstance(entity_id, str) or not entity_id:
        raise ApiError(BAD_REQUEST, "id must be a non-empty string")
    return entity_id


def _require_dict(params, key):
    value = params.get(key)
    if not isinstance(value, dict):
        raise ApiError(BAD_REQUEST, "{} must be a JSON object".format(key))
    return value


def _parse_date(raw):
    parts = raw.split("-")
    if len(parts) != 3:
        raise ValueError("date must be YYYY-MM-DD")
    return int(parts[0]), int(parts[1]), int(parts[2])


def _device_time_string():
    now = time.localtime()
    return "{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}".format(
        now[0], now[1], now[2], now[3], now[4], now[5])


def _memory_info():
    """Free/used heap bytes on MicroPython; None under CPython."""
    mem_free = getattr(gc, "mem_free", None)
    if mem_free is None:
        return None
    info = {"free": mem_free()}
    mem_alloc = getattr(gc, "mem_alloc", None)
    if mem_alloc is not None:
        info["allocated"] = mem_alloc()
    return info


# ── Settings validation ───────────────────────────────────────────────────────

_ALLOWED_SETTINGS_KEYS = {"city", "lat", "lon", "utc_offset_minutes",
                          "in_israel", "candle_offset", "tzais_offset"}


def _is_number(value):
    return not isinstance(value, bool) and isinstance(value, (int, float))


def _is_int(value):
    return not isinstance(value, bool) and isinstance(value, int)


def _setting_error(key, value):
    if key == "city":
        if not isinstance(value, str) or not value.strip():
            return "city must be a non-empty string"
    elif key == "lat":
        if not _is_number(value) or not -90 <= value <= 90:
            return "lat must be a number in -90..90"
    elif key == "lon":
        if not _is_number(value) or not -180 <= value <= 180:
            return "lon must be a number in -180..180"
    elif key == "utc_offset_minutes":
        if not _is_int(value) or not -840 <= value <= 840:
            return "utc_offset_minutes must be an integer in -840..840"
    elif key in ("candle_offset", "tzais_offset"):
        if not _is_int(value) or not 0 <= value <= 1440:
            return "{} must be an integer in 0..1440".format(key)
    elif key == "in_israel":
        if not isinstance(value, bool):
            return "in_israel must be a boolean"
    return None


class Api:
    """op → handler table over the application services."""

    def __init__(self, crud_service, control_service, settings_store,
                 views, device_time, status_info=None):
        self._crud = crud_service
        self._control = control_service
        self._settings = settings_store
        self._views = views
        self._device_time = device_time
        self._status_info = status_info
        self._started = time.time()

        ops = {}
        for entity in _CRUD_ENTITIES:
            self._register_crud(ops, entity)
        ops["schedules.set_enabled"] = self._set_schedule_enabled
        ops["schedules.upcoming"] = self._upcoming
        ops["control.send"] = self._control_send
        ops["settings.get"] = self._settings_get
        ops["settings.update"] = self._settings_update
        ops["settings.cities"] = self._cities
        ops["status.get"] = self._status
        ops["today.get"] = self._today
        ops["time.set"] = self._time_set
        self._ops = ops

    def ops(self):
        """Sorted op names — lets a channel offer discovery/help."""
        return sorted(self._ops)

    def dispatch(self, op, params=None):
        """Run ``op`` with ``params`` (a dict) and return its result data.

        Raises ApiError with a transport-independent ``kind`` on any
        failure; service-level exceptions are classified here so no
        channel needs to know them.
        """
        handler = self._ops.get(op)
        if handler is None:
            raise ApiError(BAD_REQUEST, "unknown op: {}".format(op))
        if params is None:
            params = {}
        if not isinstance(params, dict):
            raise ApiError(BAD_REQUEST, "params must be a JSON object")
        try:
            return handler(params)
        except ApiError:
            raise
        except NotFoundError as exc:
            raise ApiError(NOT_FOUND, str(exc))
        except InUseError as exc:
            raise ApiError(CONFLICT, str(exc))
        except ClockUnsupportedError as exc:
            raise ApiError(UNSUPPORTED, str(exc))
        except (DeviceValidationError, ScheduleValidationError, ValueError) as exc:
            raise ApiError(BAD_REQUEST, str(exc))
        except Exception:
            raise ApiError(INTERNAL, "internal error")

    # ── CRUD ──────────────────────────────────────────────────────────────────

    def _register_crud(self, ops, entity):
        def list_(params):
            return self._crud.list(entity)

        def create(params):
            return self._crud.create(entity, _require_dict(params, "data"))

        def update(params):
            return self._crud.update(
                entity, _require_id(params), _require_dict(params, "data"))

        def delete(params):
            self._crud.delete(entity, _require_id(params))
            return None

        ops[entity + ".list"] = list_
        ops[entity + ".create"] = create
        ops[entity + ".update"] = update
        ops[entity + ".delete"] = delete

    # ── Schedules ─────────────────────────────────────────────────────────────

    def _set_schedule_enabled(self, params):
        enabled = params.get("enabled")
        if not isinstance(enabled, bool):
            raise ApiError(BAD_REQUEST, "enabled must be a boolean")
        schedule = self._crud.get("schedules", _require_id(params))
        schedule["enabled"] = enabled
        return self._crud.update("schedules", schedule["id"], schedule)

    def _upcoming(self, params):
        days = params.get("days", 3)
        if not _is_int(days):
            raise ApiError(BAD_REQUEST, "days must be an integer")
        if not 1 <= days <= _MAX_PREVIEW_DAYS:
            raise ApiError(
                BAD_REQUEST, "days must be in 1..{}".format(_MAX_PREVIEW_DAYS))
        if self._views.repository is None:
            raise ApiError(
                UNSUPPORTED, "upcoming preview requires persistent storage")
        events, errors = self._views.upcoming_events(self._settings.get(), days)
        return {"days": days, "events": events, "planner_errors": errors}

    # ── Control ───────────────────────────────────────────────────────────────

    def _control_send(self, params):
        return self._control.send(
            target_type=params.get("target_type"),
            target_id=params.get("target_id"),
            action_type=params.get("action_type"),
        )

    # ── Settings ──────────────────────────────────────────────────────────────

    def _settings_get(self, params):
        data = self._settings.get()
        data["device_time"] = _device_time_string()
        return data

    def _settings_update(self, params):
        data = _require_dict(params, "data")
        unknown = set(data.keys()) - _ALLOWED_SETTINGS_KEYS
        if unknown:
            raise ApiError(
                BAD_REQUEST,
                "unknown settings keys: {}".format(", ".join(sorted(unknown))))
        for key, value in data.items():
            message = _setting_error(key, value)
            if message:
                raise ApiError(BAD_REQUEST, message)
        self._settings.update(data)
        return self._settings.get()

    def _cities(self, params):
        cities = []
        for city_id, city in load_cities().items():
            entry = {"id": city_id}
            entry.update(city)
            cities.append(entry)
        cities.sort(key=lambda c: c["name_he"])
        return cities

    # ── Status / today / time ─────────────────────────────────────────────────

    def _status(self, params):
        now = time.localtime()
        data = {
            "app_version": APP_VERSION,
            "device_time": _device_time_string(),
            "uptime_seconds": int(time.time() - self._started),
            "settings_load_error": getattr(self._settings, "load_error", None),
            "memory": _memory_info(),
            # A fresh MicroPython boot reads 2000-01-01 until the RTC is set.
            "clock_unset": now[0] < 2013,
        }
        if self._status_info is not None:
            try:
                info = (self._status_info()
                        if callable(self._status_info) else self._status_info)
                if isinstance(info, dict):
                    data.update(info)
            except Exception as exc:
                data["extra_info_error"] = str(exc)
        return data

    def _today(self, params):
        raw = params.get("date")
        try:
            settings = self._settings.get()
            if raw:
                if not isinstance(raw, str):
                    raise ValueError("date must be YYYY-MM-DD")
                year, month, day = _parse_date(raw)
            else:
                year, month, day = self._views.local_today(settings)
            return self._views.today_view(settings, year, month, day)
        except (KeyError, TypeError) as exc:
            # Malformed settings values surface as lookup/type errors deep in
            # the zmanim math; report them as bad input, not a server fault.
            raise ApiError(BAD_REQUEST, str(exc))

    def _time_set(self, params):
        return {"device_time": self._device_time.set_time(params)}
