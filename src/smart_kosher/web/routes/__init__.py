"""HTTP adapter — maps URLs and methods onto the Api dispatcher.

The only logic that belongs here is transport translation: JSON body
parsing, query-string conversion, and ApiError.kind → HTTP status. Input
validation and error classification live in application/api.py.
"""

from ...application.api import (
    BAD_REQUEST,
    CONFLICT,
    INTERNAL,
    NOT_FOUND,
    UNSUPPORTED,
    ApiError,
)
from ..responses import err, ok

_HTTP_STATUS = {
    BAD_REQUEST: 400,
    NOT_FOUND: 404,
    CONFLICT: 409,
    UNSUPPORTED: 501,
    INTERNAL: 500,
}


def require_json_body(req):
    try:
        body = req.json
    except Exception:
        return None, err("request body must be valid JSON")
    if not isinstance(body, dict):
        return None, err("request body must be a JSON object")
    return body, None


async def _result(api, op, params=None, created=False):
    try:
        data = await api.dispatch(op, params)
    except ApiError as exc:
        return err(str(exc), _HTTP_STATUS.get(exc.kind, 500))
    return ok(data, 201 if created else 200)


def _register_crud(app, api, entity):
    base = "/api/" + entity

    @app.get(base)
    async def list_(req, _entity=entity):
        return await _result(api, _entity + ".list")

    @app.post(base)
    async def create(req, _entity=entity):
        body, error = require_json_body(req)
        if error:
            return error
        return await _result(api, _entity + ".create", {"data": body}, created=True)

    @app.put(base + "/<entity_id>")
    async def update(req, entity_id, _entity=entity):
        body, error = require_json_body(req)
        if error:
            return error
        return await _result(api, _entity + ".update",
                       {"id": entity_id, "data": body})

    @app.delete(base + "/<entity_id>")
    async def delete(req, entity_id, _entity=entity):
        return await _result(api, _entity + ".delete", {"id": entity_id})


def register_all(app, api):
    for entity in ("zones", "endpoints", "groups", "schedules"):
        _register_crud(app, api, entity)

    @app.get("/api/schedules/upcoming")
    async def upcoming(req):
        raw = req.args.get("days", "3")
        try:
            days = int(raw)
        except ValueError:
            return err("days must be an integer")
        return await _result(api, "schedules.upcoming", {"days": days})

    @app.patch("/api/schedules/<schedule_id>/enabled")
    async def set_enabled(req, schedule_id):
        body, error = require_json_body(req)
        if error:
            return error
        return await _result(api, "schedules.set_enabled",
                       {"id": schedule_id, "enabled": body.get("enabled")})

    @app.post("/api/control")
    async def control_send(req):
        body, error = require_json_body(req)
        if error:
            return error
        return await _result(api, "control.send", body)

    # Radio registry + pairing. The ops exist only when a real gateway is
    # wired; without one the dispatcher answers unknown-op (400), which is
    # exactly what a simulator-backed dev server should say.
    @app.get("/api/zigbee/devices")
    async def zigbee_devices(req):
        return await _result(api, "zigbee.devices")

    @app.post("/api/zigbee/permit_join")
    async def zigbee_permit_join(req):
        body, error = require_json_body(req)
        if error:
            return error
        return await _result(api, "zigbee.permit_join", body)

    @app.get("/api/settings")
    async def settings_get(req):
        return await _result(api, "settings.get")

    @app.put("/api/settings")
    async def settings_update(req):
        body, error = require_json_body(req)
        if error:
            return error
        return await _result(api, "settings.update", {"data": body})

    @app.get("/api/settings/cities")
    async def cities(req):
        return await _result(api, "settings.cities")

    @app.get("/api/status")
    async def status_get(req):
        return await _result(api, "status.get")

    @app.get("/api/today")
    async def today_get(req):
        return await _result(api, "today.get", {"date": req.args.get("date")})

    @app.post("/api/time")
    async def time_set(req):
        body, error = require_json_body(req)
        if error:
            return error
        return await _result(api, "time.set", body)
