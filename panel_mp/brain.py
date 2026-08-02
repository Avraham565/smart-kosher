# In-process composition root for the wall panel (product A).
#
# The CrowPanel runs BOTH the UI (LVGL, flat modules at the device root) and the
# brain (the smart_kosher package under /lib) in one MicroPython process. This
# module builds the brain's single command surface -- application.api.Api -- and
# returns it so the UI can call ``await api.dispatch(op, params)`` directly, in
# memory, with no HTTP/serial hop (see bridge.py for the sync-callback glue).
#
# This is deliberately NOT the composition in deploy/atoms3/main.py, which wires
# the same services for product B (headless AtomS3). Two differences are
# load-bearing here:
#   * No Microdot/HTTP channel and no ``create_app`` -- the panel is its own
#     client. The Api is still built once, so a home-LAN HTTP channel remains a
#     future flip-switch (web.server.create_app(api=api)), not a rewrite.
#   * No gc.collect()/gc.threshold() strategy. On this RGB driver, forcing a
#     collection after rendering starts frees a partial draw buffer the core-0
#     copy task still points at -> LoadProhibited boot-loop (see memory
#     panel-mp-rendering). The AtomS3 has no PSRAM and no RGB scanout, so there
#     that strategy is correct; here it is forbidden. We rely on 8MB PSRAM +
#     default automatic GC.

from smart_kosher.adapters import (
    H2Simulator,
    MachineRtcClock,
    SettingsStore,
    has_rtc,
)
from smart_kosher.adapters.json_repository import JsonEventJournal, JsonRepository
from smart_kosher.application.api import Api
from smart_kosher.application.control_service import ControlService
from smart_kosher.application.crud_service import CrudService
from smart_kosher.application.device_time import DeviceTimeService
from smart_kosher.application.executor import Executor
from smart_kosher.application.views import ViewService

DATA_DIR = "/data"

# Jerusalem pilot defaults; persisted to /data/settings.json on first change.
# candle_offset is a fixed product rule (candle-lighting / Shabbat entry = 20 min
# before sunset), not a per-community knob -- there is no UI to change it.
_SETTINGS_DEFAULTS = {
    "city": "ירושלים",
    "lat": 31.7683,
    "lon": 35.2137,
    "utc_offset_minutes": 120,
    "candle_offset": 20,
    "tzais_offset": 40,
    "in_israel": True,
}

# The journal keeps records as Python objects in RAM. Even with PSRAM there is
# no reason to grow it unbounded; a couple of pilot days fit in a small bound.
_JOURNAL_MAX_RECORDS = 128


class Brain:
    """The composed brain: one Api plus the handles the UI/refresh tasks need."""

    def __init__(self, api, repository, settings, views, gateway):
        self.api = api
        self.repository = repository
        self.settings = settings
        self.views = views
        self.gateway = gateway


def _status_info_for(gateway):
    """A status.get extra-info source: storage kind plus whatever the gateway
    chooses to report (the real ZigbeeGateway exposes link liveness; the
    simulator exposes nothing)."""
    def status_info():
        info = {"storage": "json"}
        probe = getattr(gateway, "status_info", None)
        if callable(probe):
            try:
                info.update(probe())
            except Exception as exc:
                info["gateway_status_error"] = str(exc)
        return info
    return status_info


_AUTO = object()   # sentinel: pick the platform clock automatically


def create(data_dir=DATA_DIR, repository=None, gateway=None, defaults=None,
           zigbee=False, clock=_AUTO):
    """Compose the in-process brain and return a :class:`Brain`.

    ``gateway`` defaults to the H2 simulator so control ops resolve
    deterministically until the CrowPanel's H2 UART is wired; pass a real
    ZigbeeGateway together with ``zigbee=True`` to enable the radio and the
    pairing ops. ``repository`` may be injected so the caller can build a
    hardware gateway against the same repo (main.py does this -- the gateway
    resolves endpoints/groups through it); it defaults to a JSON repo on
    ``data_dir``. No HTTP channel and no forced GC are wired here -- both are
    deliberate (see the module header).
    """
    if repository is None:
        repository = JsonRepository(data_dir)
    journal = JsonEventJournal(repository, max_records=_JOURNAL_MAX_RECORDS)
    if gateway is None:
        gateway = H2Simulator()
    executor = Executor(gateway, journal)
    crud = CrudService(repository)
    control = ControlService(executor, repository)
    settings = SettingsStore(
        data_dir + "/settings.json",
        defaults=_SETTINGS_DEFAULTS if defaults is None else defaults,
    )
    views = ViewService(repository)

    # A settable clock only when the platform has one; DeviceTimeService(None)
    # then reports the clock as unsupported instead of crashing. Tests inject a
    # fake SettableClock so time.set is exercisable off-device.
    if clock is _AUTO:
        clock = MachineRtcClock() if has_rtc() else None

    api = Api(
        crud, control, settings,
        views=views,
        device_time=DeviceTimeService(clock),
        status_info=_status_info_for(gateway),
        zigbee=gateway if zigbee else None,
    )
    return Brain(api, repository, settings, views, gateway)
