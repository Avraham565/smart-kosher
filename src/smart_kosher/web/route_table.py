"""The REST surface, declared once.

Every REST call has two ends, and until this table existed each end carried
its own copy of the mapping. The hub registered URLs onto ops in
``web/routes``; the desktop client, which has to make the same call travel
over USB when there is no network, re-implemented the same mapping by hand in
``apps/desktop/bridge.rest_to_op``. Its docstring said so outright -- "mirrors the
hub's own HTTP adapter" -- and nothing checked that the mirror stayed true.

A route added to one side and forgotten on the other does not fail loudly: the
feature works over WiFi and answers 404 over USB, in silence, and the cable
most people test with is the one that works.

So the mapping is data now, and both ends read it:

    hub     web/routes.register_all  -> registers each Route on microdot
    client  apps/desktop/bridge.rest_to_op -> matches a URL against the same Routes

Adding a route here is the whole change; both transports pick it up.

Deliberately free of microdot and of anything device-specific -- the desktop
client imports this module, and it must stay importable anywhere the core is.
"""

from ..application.api import (
    BAD_REQUEST,
    CONFLICT,
    INTERNAL,
    NOT_FOUND,
    UNSUPPORTED,
)
from ..domain.entities import CONFIG_ENTITY_TYPES

# Methods whose body is a JSON object the handler needs. Everything else
# carries its parameters in the path or the query string.
BODY_METHODS = ("POST", "PUT", "PATCH")

# ApiError.kind -> HTTP status. The other half of the mapping that used to be
# written twice: the hub renders a kind into a status here, and the client
# reads the status back off a serial reply that carries the kind verbatim.
# One table, so the two directions cannot disagree.
HTTP_STATUS = {
    BAD_REQUEST: 400,
    NOT_FOUND: 404,
    CONFLICT: 409,
    UNSUPPORTED: 501,
    INTERNAL: 500,
}


class Route:
    """One REST endpoint: how to recognise it, and what op it becomes.

    ``params(path_vars, query, body)`` builds the op's parameters, where
    ``path_vars`` maps a ``<name>`` in the pattern to the value found there,
    ``query`` is a flat ``{name: string}`` of the query string, and ``body`` is
    the parsed JSON object (None when the method carries no body).
    """

    def __init__(self, method, pattern, op, params=None, created=False):
        self.method = method
        self.pattern = pattern
        self.op = op
        self.params = _no_params if params is None else params
        # 201 rather than 200; the one property of a response that belongs to
        # the route rather than to the op.
        self.created = created
        self.parts = tuple(part for part in pattern.split("/") if part)

    def wants_body(self):
        return self.method in BODY_METHODS

    def match(self, parts):
        """Path segments -> ``path_vars`` dict, or None when this is not it."""
        if len(parts) != len(self.parts):
            return None
        path_vars = {}
        for expected, actual in zip(self.parts, parts):
            if expected[:1] == "<" and expected[-1:] == ">":
                path_vars[expected[1:-1]] = actual
            elif expected != actual:
                return None
        return path_vars


# ── parameter builders ───────────────────────────────────────────────────────

def _no_params(path_vars, query, body):
    return {}


def _body_params(path_vars, query, body):
    return body or {}


def _wrapped_body(path_vars, query, body):
    return {"data": body or {}}


def _id_only(path_vars, query, body):
    return {"id": path_vars["id"]}


def _id_and_body(path_vars, query, body):
    return {"id": path_vars["id"], "data": body or {}}


def _set_enabled(path_vars, query, body):
    return {"id": path_vars["id"], "enabled": (body or {}).get("enabled")}


def _upcoming(path_vars, query, body):
    # A query string is always text, so the conversion belongs here. A value
    # that is not a number is passed through untouched rather than rejected
    # locally: Api already owns that message ("days must be an integer"), and
    # producing it in two places is how the two ends drifted in the first
    # place.
    raw = query.get("days", "3")
    try:
        return {"days": int(raw)}
    except (TypeError, ValueError):
        return {"days": raw}


def _today(path_vars, query, body):
    return {"date": query.get("date")}


# ── the table ────────────────────────────────────────────────────────────────

def _crud_routes(entity):
    base = "/api/" + entity
    return (
        Route("GET", base, entity + ".list"),
        Route("POST", base, entity + ".create", _wrapped_body, created=True),
        Route("PUT", base + "/<id>", entity + ".update", _id_and_body),
        Route("DELETE", base + "/<id>", entity + ".delete", _id_only),
    )


def _build_routes():
    routes = [
        # Fixed paths first. Nothing here currently collides with the CRUD
        # patterns -- they differ in segment count or method -- but matching is
        # first-wins, so a specific path stays ahead of a parameterised one.
        Route("GET", "/api/schedules/upcoming", "schedules.upcoming", _upcoming),
        Route("PATCH", "/api/schedules/<id>/enabled",
              "schedules.set_enabled", _set_enabled),
        Route("POST", "/api/control", "control.send", _body_params),
        # Radio registry + pairing. The ops exist only when a real gateway is
        # wired; without one the dispatcher answers unknown-op (400), which is
        # exactly what a simulator-backed dev server should say.
        Route("GET", "/api/zigbee/devices", "zigbee.devices"),
        Route("POST", "/api/zigbee/permit_join",
              "zigbee.permit_join", _body_params),
        Route("GET", "/api/settings", "settings.get"),
        Route("PUT", "/api/settings", "settings.update", _wrapped_body),
        Route("GET", "/api/settings/cities", "settings.cities"),
        Route("GET", "/api/status", "status.get"),
        Route("GET", "/api/today", "today.get", _today),
        Route("POST", "/api/time", "time.set", _body_params),
    ]
    for entity in CONFIG_ENTITY_TYPES:
        routes.extend(_crud_routes(entity))
    return tuple(routes)


ROUTES = _build_routes()


def resolve(method, path):
    """Find the route serving ``method path``.

    Returns ``(route, path_vars)``, or ``(None, None)`` when nothing matches --
    which the caller renders as a 404.
    """
    parts = tuple(part for part in path.split("/") if part)
    for route in ROUTES:
        if route.method != method:
            continue
        path_vars = route.match(parts)
        if path_vars is not None:
            return route, path_vars
    return None, None
