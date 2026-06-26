"""Routes for /api/control — manual immediate device commands."""

from ..responses import ok
from . import handle_error, require_json_body


def register(app, control_service):

    @app.post("/api/control")
    async def send_command(req):
        body, error = require_json_body(req)
        if error:
            return error
        try:
            result = control_service.send(
                target_type=body.get("target_type"),
                target_id=body.get("target_id"),
                action_type=body.get("action_type"),
            )
            return ok(result)
        except Exception as exc:
            return handle_error(exc)
