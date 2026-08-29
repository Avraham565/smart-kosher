"""Transport-agnostic command surface — the single API every channel speaks.

Each channel (HTTP routes, USB serial, future MQTT) translates its own
envelope into ``Api.dispatch(op, params)`` and renders ``ApiError.kind``
back into its own status vocabulary. Business rules stay in the services;
this module only routes ops, validates parameter shape, and classifies
errors.
"""

import gc
import time

from ..data import load_cities, resolve_city
from ..domain.devices import DeviceValidationError
from ..domain.entities import CONFIG_ENTITY_TYPES
from ..domain.schedules import ScheduleValidationError
from ..ports.clock import MIN_VALID_YEAR
from ..zmanim import CANDLE_OFFSET_MINUTES
from .crud_service import InUseError, NotFoundError
from .device_time import ClockUnsupportedError

APP_VERSION = "0.1.0"

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

# candle_offset is NOT here: it is a fixed product rule (18 min before sunset),
# identical across Israel, with no UI and no per-community knob. A write to it is
# rejected as an unknown key rather than silently accepted into a file nothing
# reads. tzais_offset is not here either, and no longer exists anywhere: Shabbat
# exit is an angle (8.5 degrees below the horizon), not a minute count.
_ALLOWED_SETTINGS_KEYS = {"city", "lat", "lon", "elevation",
                          "utc_offset_minutes", "in_israel"}

# Reported on read so the display shows what is actually computed. A device
# whose settings.json predates the decision still has the old numbers stored;
# echoing those back would show a Shabbat time the system does not use.
_FIXED_SETTINGS = {"candle_offset": CANDLE_OFFSET_MINUTES}


def _with_city_geography(data):
    """Expand a packaged city into the coordinates it stands for.

    Picking a city is picking a location, so the three numbers that decide the
    zmanim travel with the name. Without this, changing only ``city`` leaves the
    previous city's latitude, longitude and elevation in place and every zman
    stays wrong -- which is precisely the failure that ran for years when the
    per-city elevations in cities.json were never read by anything.

    Explicit coordinates in the same request win: a caller sending a city name
    alongside its own lat/lon is describing somewhere the list does not cover,
    and that is allowed.
    """
    if "city" not in data:
        return data
    resolved = resolve_city(data["city"])
    if resolved is None:
        return data

    _, city = resolved
    expanded = dict(data)
    expanded["city"] = city["name_he"]
    for field, key in (("lat", "lat"), ("lon", "lon"), ("elevation", "elevation")):
        if key not in data:
            expanded[key] = city[field]
    return expanded


def _is_awaitable(value):
    """True for coroutine objects on both runtimes: CPython coroutines
    have __await__; MicroPython coroutines are generators (send/throw).
    Plain data (dict/list/str/None) has neither."""
    return (hasattr(value, "__await__")
            or (hasattr(value, "send") and hasattr(value, "throw")))


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
    elif key == "elevation":
        # Non-negative mirrors the reference implementation, which rejects a
        # negative elevation outright. Tiberias and the Dead Sea shore are below
        # sea level and are configured as 0, which is what it would compute for
        # them anyway. The ceiling is well clear of Israel's highest inhabited
        # ground and only guards against a typo becoming a zman.
        if not _is_number(value) or not 0 <= value <= 9000:
            return "elevation must be a number in 0..9000"
    elif key == "utc_offset_minutes":
        if not _is_int(value) or not -840 <= value <= 840:
            return "utc_offset_minutes must be an integer in -840..840"
    elif key == "in_israel":
        if not isinstance(value, bool):
            return "in_israel must be a boolean"
    return None


class Api:
    """op → handler table over the application services."""

    def __init__(self, crud_service, control_service, settings_store,
                 views, device_time, status_info=None, zigbee=None):
        self._crud = crud_service
        self._control = control_service
        self._settings = settings_store
        self._views = views
        self._device_time = device_time
        self._status_info = status_info
        self._zigbee = zigbee
        self._started = time.time()

        ops = {}
        for entity in CONFIG_ENTITY_TYPES:
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
        if zigbee is not None:
            # Pairing/registry surface — only when a real radio gateway is
            # wired (the simulator has nothing to pair).
            ops["zigbee.devices"] = self._zigbee_devices
            ops["zigbee.permit_join"] = self._zigbee_permit_join
            ops["zigbee.discard"] = self._zigbee_discard
            ops["zigbee.identify"] = self._zigbee_identify
        self._ops = ops

    def ops(self):
        """Sorted op names — lets a channel offer discovery/help."""
        return sorted(self._ops)

    async def dispatch(self, op, params=None):
        """Run ``op`` with ``params`` (a dict) and return its result data.

        Async because device-facing ops await a radio round-trip; plain
        sync handlers are returned as-is. Raises ApiError with a
        transport-independent ``kind`` on any failure; service-level
        exceptions are classified here so no channel needs to know them.
        """
        handler = self._ops.get(op)
        if handler is None:
            raise ApiError(BAD_REQUEST, "unknown op: {}".format(op))
        if params is None:
            params = {}
        if not isinstance(params, dict):
            raise ApiError(BAD_REQUEST, "params must be a JSON object")
        try:
            data = handler(params)
            if _is_awaitable(data):
                data = await data
            return data
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

        async def delete(params):
            entity_id = _require_id(params)
            ieee = self._radio_identity(entity, entity_id)
            # The entity goes first and unconditionally. Whether the radio can
            # be told is a separate question, and a device that is unplugged
            # must not keep its row on the screen.
            self._crud.delete(entity, entity_id)
            if ieee is not None:
                await self._release_radio_device(ieee)
            return None

        ops[entity + ".list"] = list_
        ops[entity + ".create"] = create
        ops[entity + ".update"] = update
        ops[entity + ".delete"] = delete

    # ── Deleting a device must also remove it from the radio ─────────────────

    def _radio_identity(self, entity, entity_id):
        """The ieee address a soon-to-be-deleted endpoint occupies, if any."""
        if entity != "endpoints" or self._zigbee is None:
            return None
        try:
            return (self._crud.get(entity, entity_id) or {}).get("ieee_address")
        except Exception:
            return None

    async def _release_radio_device(self, ieee):
        """Tell the coordinator to drop a device once nothing refers to it.

        Deleting an endpoint used to remove only this hub's record of it: the
        device stayed joined to the mesh, kept its slot among the
        coordinator's children, and would reappear in the registry the next
        time it announced itself. Removing it from the panel now removes it
        from the network.

        Guarded by a reference check because one physical device can back
        several endpoints -- a two-gang switch is two entities on one radio,
        and deleting one gang must not evict the other.
        """
        for entity in self._crud.list("endpoints"):
            if entity.get("ieee_address") == ieee:
                return          # another endpoint still uses this device
        try:
            # Started, not awaited. The coordinator gives a leave 8000ms before
            # it answers, and a user who pressed delete must not watch a screen
            # for that -- the entity is already gone and the verdict only
            # decides whether the registry record is earned. Waiting here also
            # forced the wait to be short enough for a person, which is how the
            # verdict came to be thrown away.
            self._zigbee.start_forget_device(ieee)
        except Exception as exc:
            # The entity is already gone; a radio that cannot be reached must
            # not turn a successful delete into an error the user sees.
            self._log_radio_error("forget_device", exc)

    @staticmethod
    def _log_radio_error(what, exc):
        print("zigbee {} failed: {}".format(what, exc))

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
        confirm_ms = params.get("confirm_ms")
        if confirm_ms is not None and (
                not _is_int(confirm_ms) or not 1 <= confirm_ms <= 15000):
            raise ApiError(BAD_REQUEST,
                           "confirm_ms must be an integer in 1..15000")
        return self._control.send(
            target_type=params.get("target_type"),
            target_id=params.get("target_id"),
            action_type=params.get("action_type"),
            confirm_ms=confirm_ms,
        )

    # ── Zigbee pairing / registry ─────────────────────────────────────────────

    def _zigbee_devices(self, params):
        return self._zigbee.devices()

    def _zigbee_permit_join(self, params):
        duration = params.get("duration", 180)
        if not _is_int(duration) or not 1 <= duration <= 254:
            raise ApiError(BAD_REQUEST, "duration must be an integer in 1..254")
        return self._zigbee.permit_join(duration)

    def _zigbee_discard(self, params):
        """Take a device off the pairing list without touching the network.

        Refused when any entity still points at it. _release_radio_device makes
        the same check on the delete path, and this needs its own rather than
        borrowing it: a device can be adopted between the row being drawn and
        the button being pressed, and discarding it then would leave an entity
        whose radio the hub no longer knows.
        """
        ieee = params.get("ieee")
        if not isinstance(ieee, str) or not ieee:
            raise ApiError(BAD_REQUEST, "ieee must be a non-empty string")
        for entity in self._crud.list("endpoints"):
            if entity.get("ieee_address") == ieee:
                raise ApiError(
                    CONFLICT,
                    "device is in use by an endpoint; delete it there instead")
        return self._zigbee.discard_device(ieee)

    async def _zigbee_identify(self, params):
        """Flip one gang and put it back, so the user can see which is which.

        The whole pulse happens in the gateway, restore included. Split into a
        read op and a write op for the UI to assemble, anything that interrupts
        between them leaves a real load switched on in someone's house.
        """
        ieee = params.get("ieee")
        endpoint = params.get("endpoint")
        if not isinstance(ieee, str) or not ieee:
            raise ApiError(BAD_REQUEST, "ieee must be a non-empty string")
        if not _is_int(endpoint) or not 1 <= endpoint <= 254:
            raise ApiError(BAD_REQUEST,
                           "endpoint must be an integer in 1..254")
        return await self._zigbee.identify(ieee, endpoint)

    # ── Settings ──────────────────────────────────────────────────────────────

    def _settings_get(self, params):
        # Project onto the keys this API defines rather than echoing storage.
        # A device provisioned before a rule changed still carries the retired
        # keys in its settings.json, and reporting those back would show a
        # Shabbat time the system does not compute -- tzais_offset sat there as
        # a flat 40 long after Shabbat exit became an angle. The write path
        # already rejects unknown keys; this is the same guarantee outbound.
        stored = self._settings.get()
        data = {key: value for key, value in stored.items()
                if key in _ALLOWED_SETTINGS_KEYS}
        data["device_time"] = _device_time_string()
        data.update(_FIXED_SETTINGS)
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
        self._settings.update(_with_city_geography(data))
        # The same projection the read path applies, not the raw store. A
        # device provisioned before a rule changed still carries the retired
        # keys, so echoing storage here showed a candle_offset of 40 straight
        # after a city edit while the system went on lighting at 18 -- the one
        # number the user had just been looking at, and the wrong one.
        return self._settings_get(params)

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
            "zigbee_registry_load_error": (
                getattr(self._zigbee, "registry_load_error", None)
                if self._zigbee is not None else None),
            "memory": _memory_info(),
            # A fresh MicroPython boot reads 2000-01-01 until the RTC is set.
            "clock_unset": now[0] < MIN_VALID_YEAR,
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
