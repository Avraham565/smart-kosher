"""Microdot application factory — wires routes, static files, and services."""

import os

from microdot import Microdot, send_file

from .routes import zones, endpoints, groups, schedules, control, settings

try:
    _STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
except Exception:
    _STATIC = "static"


def create_app(crud_service, control_service, settings_store):
    app = Microdot()

    zones.register(app, crud_service)
    endpoints.register(app, crud_service)
    groups.register(app, crud_service)
    schedules.register(app, crud_service)
    control.register(app, control_service)
    settings.register(app, settings_store)

    @app.get("/")
    async def index(req):
        return send_file(_STATIC + "/index.html")

    @app.get("/static/<path:path>")
    async def static_file(req, path):
        return send_file(_STATIC + "/" + path)

    return app
