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
    """The parsed body, or an error response.

    An *absent* body is not an error. It becomes {}, which is what the route
    table's own builders already do with ``body or {}`` -- and that was the
    whole divergence: the same PUT with no body was a 400 here and a silent
    no-op over USB. Microdot returns None for a request with no JSON content
    type rather than raising, so absence used to fall into the "not a dict"
    branch and be reported as bad JSON, which it also was not.

    A body that is present and unparseable, or present and not an object,
    stays a 400 -- those are real client errors and both transports agree on
    them.
    """
    try:
        body = req.json
    except Exception:
        return None, err("request body must be valid JSON")
    if body is None:
        # Microdot answers None both for "there is no body" and for "there is
        # a body and I will not parse it as JSON" -- a text/plain payload, for
        # instance. Only the first of those is benign, so they are told apart
        # here rather than both being waved through.
        if req.body:
            return None, err("request body must be valid JSON")
        return {}, None
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
