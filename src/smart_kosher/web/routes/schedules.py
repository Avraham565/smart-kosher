"""Routes for /api/schedules — CRUD + enabled toggle."""

from ..responses import ok, err
from . import handle_error, require_json_body


def register(app, crud_service):

    @app.get("/api/schedules")
    async def list_schedules(req):
        return ok(crud_service.list("schedules"))

    @app.post("/api/schedules")
    async def create_schedule(req):
        body, error = require_json_body(req)
        if error:
            return error
        try:
            return ok(crud_service.create("schedules", body), 201)
        except Exception as exc:
            return handle_error(exc)

    @app.put("/api/schedules/<schedule_id>")
    async def update_schedule(req, schedule_id):
        body, error = require_json_body(req)
        if error:
            return error
        try:
            return ok(crud_service.update("schedules", schedule_id, body))
        except Exception as exc:
            return handle_error(exc)

    @app.patch("/api/schedules/<schedule_id>/enabled")
    async def set_enabled(req, schedule_id):
        body, error = require_json_body(req)
        if error:
            return error
        enabled = body.get("enabled")
        if not isinstance(enabled, bool):
            return err("enabled must be a boolean")
        try:
            schedule = crud_service.get("schedules", schedule_id)
            schedule["enabled"] = enabled
            return ok(crud_service.update("schedules", schedule_id, schedule))
        except Exception as exc:
            return handle_error(exc)

    @app.delete("/api/schedules/<schedule_id>")
    async def delete_schedule(req, schedule_id):
        try:
            crud_service.delete("schedules", schedule_id)
            return ok()
        except Exception as exc:
            return handle_error(exc)
