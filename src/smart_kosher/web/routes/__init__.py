"""Shared error handler for all API routes."""

from ..responses import err, not_found
from ...application.crud_service import InUseError, NotFoundError
from ...domain.devices import DeviceValidationError
from ...domain.schedules import ScheduleValidationError


def handle_error(exc):
    if isinstance(exc, NotFoundError):
        return not_found(str(exc))
    if isinstance(exc, InUseError):
        return err(str(exc), 409)
    if isinstance(exc, (DeviceValidationError, ScheduleValidationError, ValueError)):
        return err(str(exc))
    return err("internal error", 500)


def require_json_body(req):
    try:
        body = req.json
    except Exception:
        return None, err("request body must be valid JSON")
    if not isinstance(body, dict):
        return None, err("request body must be a JSON object")
    return body, None
