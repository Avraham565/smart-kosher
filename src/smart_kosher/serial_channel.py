"""USB-serial channel — line-delimited JSON over the device's USB CDC.

Protocol: one JSON object per line, in both directions.

Request:   {"op": "zones.list", "params": {...}, "id": <any, optional>}
Response:  {"ok": true, "data": ...}
           {"ok": false, "kind": "bad_request", "error": "..."}
The request "id", when present, is echoed back on the response so clients
can correlate. ``op`` names and ``params`` shapes are exactly the Api
dispatcher's; ``kind`` uses its error vocabulary.

The channel shares the USB CDC with MicroPython's console, so boot
messages and crash traces appear between responses: clients must ignore
any line that does not parse as a JSON object with an "ok" key.

``handle_line`` is the pure core (tested on CPython); ``serve`` is the
device-side read loop.
"""

try:
    import ujson as json
except ImportError:
    import json

from .application.api import ApiError, BAD_REQUEST, INTERNAL


def _error(message, kind=BAD_REQUEST):
    return {"ok": False, "kind": kind, "error": message}


async def handle_line(api, line, extra_ops=None):
    """Process one request line; returns the response as a JSON string.

    ``extra_ops`` maps op names to ``handler(params) -> data`` for
    device-only commands (wifi provisioning, reboot) that don't belong in
    the shared Api. They may raise ApiError; anything else is reported as
    internal.
    """
    try:
        request = json.loads(line)
    except ValueError:
        return json.dumps(_error("request must be valid JSON"))
    if not isinstance(request, dict):
        return json.dumps(_error("request must be a JSON object"))

    op = request.get("op")
    params = request.get("params")
    if not isinstance(op, str):
        response = _error("op must be a string")
    else:
        try:
            if op == "ops.list":
                data = api.ops() + sorted(extra_ops or {})
            elif extra_ops is not None and op in extra_ops:
                if params is None:
                    params = {}
                if not isinstance(params, dict):
                    raise ApiError(BAD_REQUEST, "params must be a JSON object")
                data = extra_ops[op](params)
            else:
                data = await api.dispatch(op, params)
            response = {"ok": True, "data": data}
        except ApiError as exc:
            response = _error(str(exc), exc.kind)
        except Exception:
            response = _error("internal error", INTERNAL)

    if "id" in request:
        response["id"] = request["id"]
    return json.dumps(response)


# The USB-Serial/JTAG console is lossy: when a write outruns its small TX
# ring buffer, MicroPython DROPS the excess bytes rather than block. A big
# response (a grown schedules list) came out with a hole in the middle,
# the client could not parse it, and every request after an "add" hung to
# its timeout. Write in small chunks and yield so the host drains the
# buffer between them.
_WRITE_CHUNK = 64
_WRITE_PAUSE_S = 0.004


async def _write_response(out, text):
    import asyncio

    for i in range(0, len(text), _WRITE_CHUNK):
        out.write(text[i:i + _WRITE_CHUNK])
        await asyncio.sleep(_WRITE_PAUSE_S)
    out.write("\n")


async def serve(api, extra_ops=None):
    """Read requests from the USB CDC forever (device-side loop).

    Runs alongside the HTTP server on the shared asyncio loop; a request
    is handled synchronously (Api ops are all synchronous and fast).
    """
    import sys
    import asyncio

    reader = asyncio.StreamReader(sys.stdin)
    while True:
        line = await reader.readline()
        if not line:
            # EOF cannot really happen on the device CDC; yield so a
            # misbehaving stream doesn't spin the loop at 100% CPU.
            await asyncio.sleep(1)
            continue
        if isinstance(line, bytes):
            try:
                line = line.decode()
            except UnicodeError:
                continue
        line = line.strip()
        if not line:
            continue
        await _write_response(sys.stdout,
                              await handle_line(api, line, extra_ops))
