"""HTTP adapter — maps URLs and methods onto the Api dispatcher.

The only logic that belongs here is transport translation: JSON body
parsing, query-string conversion, and ApiError.kind → HTTP status. Input
validation and error classification live in application/api.py.

The URL→op mapping itself is not here either: it is data in
``web/route_table``, shared with the desktop client so the same request
behaves identically whether it arrives over WiFi or over USB.
"""

from ...application.api import ApiError
from ..responses import err, ok
from ..route_table import HTTP_STATUS, ROUTES


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
        return err(str(exc), HTTP_STATUS.get(exc.kind, 500))
    return ok(data, 201 if created else 200)


def _register(app, api, route):
    @app.route(route.pattern, methods=[route.method])
    async def handler(req, _route=route, **path_vars):
        body = None
        if _route.wants_body():
            body, error = require_json_body(req)
            if error:
                return error
        params = _route.params(path_vars, req.args, body)
        return await _result(api, _route.op, params, created=_route.created)

    return handler


def register_all(app, api):
    for route in ROUTES:
        _register(app, api, route)
