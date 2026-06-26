"""Routes for /api/endpoints — CRUD for endpoint entities."""

from ..responses import ok
from . import handle_error, require_json_body


def register(app, crud_service):

    @app.get("/api/endpoints")
    async def list_endpoints(req):
        return ok(crud_service.list("endpoints"))

    @app.post("/api/endpoints")
    async def create_endpoint(req):
        body, error = require_json_body(req)
        if error:
            return error
        try:
            return ok(crud_service.create("endpoints", body), 201)
        except Exception as exc:
            return handle_error(exc)

    @app.put("/api/endpoints/<endpoint_id>")
    async def update_endpoint(req, endpoint_id):
        body, error = require_json_body(req)
        if error:
            return error
        try:
            return ok(crud_service.update("endpoints", endpoint_id, body))
        except Exception as exc:
            return handle_error(exc)

    @app.delete("/api/endpoints/<endpoint_id>")
    async def delete_endpoint(req, endpoint_id):
        try:
            crud_service.delete("endpoints", endpoint_id)
            return ok()
        except Exception as exc:
            return handle_error(exc)
