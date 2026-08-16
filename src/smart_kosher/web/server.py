"""Microdot application factory — wires the HTTP adapter to the Api.

The hub is API-only: clients are the Windows tool / phone app over the home
network (STA), or the USB-serial channel. There is no on-device UI.
"""

import gc

from microdot import Microdot

from ..application.api import Api
from ..application.device_time import DeviceTimeService
from ..application.views import ViewService
from .routes import register_all

# MicroPython exposes gc.mem_free; CPython does not.
_IS_MICROPYTHON = hasattr(gc, "mem_free")


def create_app(crud_service, control_service, settings_store,
               repository=None, status_info=None, clock=None, api=None,
               collect_after_request=None):
    """``clock`` is a SettableClock adapter, or None when the platform has
    no settable RTC (CPython dev server / tests). Pass a prebuilt ``api``
    to share one dispatcher (and its caches) with other channels.

    ``collect_after_request`` is a **product** decision, not a platform one,
    and the caller is the only one who knows which product it is assembling.
    On product B (no PSRAM) collecting after every response is what keeps the
    heap from fragmenting; on product A the same call can free a partial draw
    buffer that core 0 is still scanning out -- the LoadProhibited boot loop
    (CLAUDE.md). ``None`` keeps the historical default of deciding by
    platform, which is wrong for product A and only safe today because the
    panel does not build an app at all. Any caller on the panel must pass
    False explicitly.
    """
    app = Microdot()

    if api is None:
        api = Api(
            crud_service, control_service, settings_store,
            views=ViewService(repository),
            device_time=DeviceTimeService(clock),
            status_info=status_info,
        )

    register_all(app, api)

    if collect_after_request is None:
        collect_after_request = _IS_MICROPYTHON

    if collect_after_request:
        # On a no-PSRAM board every request leaves allocation churn behind;
        # collecting after each response keeps the heap defragmented instead
        # of letting pressure build until an allocation fails mid-request.
        @app.after_request
        async def _collect(req, resp):
            gc.collect()
            return resp

    return app
