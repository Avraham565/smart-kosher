"""Routes for /api/groups — CRUD for group entities."""

from ..responses import ok
from . import handle_error, require_json_body


def register(app, crud_service):

    @app.get("/api/groups")
    async def list_groups(req):
        return ok(crud_service.list("groups"))

    @app.post("/api/groups")
    async def create_group(req):
        body, error = require_json_body(req)
        if error:
            return error
        try:
            return ok(crud_service.create("groups", body), 201)
        except Exception as exc:
            return handle_error(exc)

    @app.put("/api/groups/<group_id>")
    async def update_group(req, group_id):
        body, error = require_json_body(req)
        if error:
            return error
        try:
            return ok(crud_service.update("groups", group_id, body))
        except Exception as exc:
            return handle_error(exc)

    @app.delete("/api/groups/<group_id>")
    async def delete_group(req, group_id):
        try:
            crud_service.delete("groups", group_id)
            return ok()
        except Exception as exc:
            return handle_error(exc)
