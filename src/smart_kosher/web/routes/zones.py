"""Routes for /api/zones — CRUD for zone entities."""

from ..responses import ok
from . import handle_error, require_json_body


def register(app, crud_service):

    @app.get("/api/zones")
    async def list_zones(req):
        return ok(crud_service.list("zones"))

    @app.post("/api/zones")
    async def create_zone(req):
        body, error = require_json_body(req)
        if error:
            return error
        try:
            return ok(crud_service.create("zones", body), 201)
        except Exception as exc:
            return handle_error(exc)

    @app.put("/api/zones/<zone_id>")
    async def update_zone(req, zone_id):
        body, error = require_json_body(req)
        if error:
            return error
        try:
            return ok(crud_service.update("zones", zone_id, body))
        except Exception as exc:
            return handle_error(exc)

    @app.delete("/api/zones/<zone_id>")
    async def delete_zone(req, zone_id):
        try:
            crud_service.delete("zones", zone_id)
            return ok()
        except Exception as exc:
            return handle_error(exc)
