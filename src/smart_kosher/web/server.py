"""Microdot application factory — wires the JSON API routes to services.

The hub is API-only: clients are the Windows tool / phone app over the home
network (STA), or the USB-serial channel. There is no on-device UI.
"""

import gc

from microdot import Microdot

# MicroPython exposes gc.mem_free; CPython does not.
_IS_MICROPYTHON = hasattr(gc, "mem_free")

from .routes import (
    zones, endpoints, groups, schedules, control, settings, status, today,
    device_time,
)


def create_app(crud_service, control_service, settings_store,
               repository=None, status_info=None):
    app = Microdot()

    zones.register(app, crud_service)
    endpoints.register(app, crud_service)
    groups.register(app, crud_service)
    schedules.register(app, crud_service, repository, settings_store)
    control.register(app, control_service)
    settings.register(app, settings_store)
    status.register(app, settings_store, status_info)
    today.register(app, settings_store)
    device_time.register(app)

    if _IS_MICROPYTHON:
        # On a no-PSRAM board every request leaves allocation churn behind;
        # collecting after each response keeps the heap defragmented instead
        # of letting pressure build until an allocation fails mid-request.
        @app.after_request
        async def _collect(req, resp):
            gc.collect()
            return resp

    return app
