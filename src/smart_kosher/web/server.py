"""Microdot application factory — wires the HTTP adapter to the Api.

The hub is API-only: clients are the Windows tool / phone app over the home
network (STA), or the USB-serial channel. There is no on-device UI.
"""

import gc

from microdot import Microdot

# MicroPython exposes gc.mem_free; CPython does not.
_IS_MICROPYTHON = hasattr(gc, "mem_free")

from ..application.api import Api
from ..application.device_time import DeviceTimeService
from ..application.views import ViewService
from .routes import register_all


def create_app(crud_service, control_service, settings_store,
               repository=None, status_info=None, clock=None, api=None):
    """``clock`` is a SettableClock adapter, or None when the platform has
    no settable RTC (CPython dev server / tests). Pass a prebuilt ``api``
    to share one dispatcher (and its caches) with other channels."""
    app = Microdot()

    if api is None:
        api = Api(
            crud_service, control_service, settings_store,
            views=ViewService(repository),
            device_time=DeviceTimeService(clock),
            status_info=status_info,
        )

    register_all(app, api)

    if _IS_MICROPYTHON:
        # On a no-PSRAM board every request leaves allocation churn behind;
        # collecting after each response keeps the heap defragmented instead
        # of letting pressure build until an allocation fails mid-request.
        @app.after_request
        async def _collect(req, resp):
            gc.collect()
            return resp

    return app
