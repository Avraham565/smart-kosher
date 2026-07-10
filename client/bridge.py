"""Device link layer — one interface, two transports.

The UI speaks REST (the same /api/* the hub serves over WiFi). A link
translates that to whatever transport is available:

- NetworkLink: forwards the request as-is to the hub's HTTP server.
- SerialLink: translates REST to the hub's op protocol (one JSON per
  line over USB CDC) and maps error kinds back to HTTP status codes.

Both expose ``rest(method, path, query, body) -> (status, payload)``;
SerialLink additionally exposes ``op()`` for device-only commands
(wifi.provision, system.reboot) that have no REST equivalent.
"""

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import serial
from serial.tools import list_ports

# ESP32-S3 USB-Serial/JTAG in MicroPython mode (bootloader mode is 1001).
DEVICE_VID = 0x303A
DEVICE_PID = 0x4001

_KIND_TO_STATUS = {
    "bad_request": 400,
    "not_found": 404,
    "conflict": 409,
    "unsupported": 501,
    "internal": 500,
}

_CRUD_ENTITIES = ("zones", "endpoints", "groups", "schedules")


class LinkError(Exception):
    """Transport failure (port gone, host unreachable, timeout)."""


def _is_idempotent(op_name):
    """Safe to resend when the response was lost. Creates would duplicate
    the entity and control.send would re-fire the action, so they get no
    retry; everything else is a read or an idempotent write."""
    return not (op_name.endswith(".create") or op_name == "control.send")


def find_device_ports():
    """COM ports that look like the hub, most recently attached first."""
    matches = []
    for port in list_ports.comports():
        if port.vid == DEVICE_VID and port.pid == DEVICE_PID:
            matches.append(port.device)
    return matches


def rest_to_op(method, path, query, body):
    """Translate a REST request to ``(op, params, created)`` or None.

    Mirrors the hub's own HTTP adapter (web/routes/__init__.py) so the
    serial transport behaves identically to the network one.
    """
    parts = [p for p in path.split("/") if p]
    if not parts or parts[0] != "api":
        return None
    parts = parts[1:]

    if parts == ["schedules", "upcoming"] and method == "GET":
        raw = (query.get("days") or ["3"])[0]
        try:
            days = int(raw)
        except ValueError:
            days = raw  # let the hub reject it with its own message
        return "schedules.upcoming", {"days": days}, False
    if (len(parts) == 3 and parts[0] == "schedules" and parts[2] == "enabled"
            and method == "PATCH"):
        return ("schedules.set_enabled",
                {"id": parts[1], "enabled": (body or {}).get("enabled")}, False)
    if parts == ["control"] and method == "POST":
        return "control.send", body or {}, False
    if parts == ["settings"]:
        if method == "GET":
            return "settings.get", {}, False
        if method == "PUT":
            return "settings.update", {"data": body or {}}, False
    if parts == ["settings", "cities"] and method == "GET":
        return "settings.cities", {}, False
    if parts == ["status"] and method == "GET":
        return "status.get", {}, False
    if parts == ["today"] and method == "GET":
        date = (query.get("date") or [None])[0]
        return "today.get", {"date": date}, False
    if parts == ["time"] and method == "POST":
        return "time.set", body or {}, False

    if parts and parts[0] in _CRUD_ENTITIES:
        entity = parts[0]
        if len(parts) == 1:
            if method == "GET":
                return entity + ".list", {}, False
            if method == "POST":
                return entity + ".create", {"data": body or {}}, True
        elif len(parts) == 2:
            if method == "PUT":
                return (entity + ".update",
                        {"id": parts[1], "data": body or {}}, False)
            if method == "DELETE":
                return entity + ".delete", {"id": parts[1]}, False
    return None


class SerialLink:
    mode = "serial"

    def __init__(self, port, baud=115200, read_timeout=1.0):
        try:
            # Deassert DTR/RTS *before* opening: the default assertion pulse
            # resets the ESP32-S3 over USB-Serial/JTAG, rebooting the hub
            # every time the app connects.
            self._serial = serial.Serial(None, baud, timeout=read_timeout)
            self._serial.port = port
            self._serial.dtr = False
            self._serial.rts = False
            self._serial.open()
        except (serial.SerialException, OSError) as exc:
            raise LinkError("cannot open {}: {}".format(port, exc))
        self.port = port
        self._lock = threading.Lock()
        self._next_id = 1
        time.sleep(0.3)
        self._serial.reset_input_buffer()

    def close(self):
        try:
            self._serial.close()
        except Exception:
            pass

    def describe(self):
        return {"mode": "serial", "port": self.port}

    def op(self, op_name, params=None, timeout_s=4.0, retries=None):
        """Send one op, return the hub's response dict (ok/data/error/kind).

        Console lines (boot noise, tracebacks) interleave with protocol
        lines on the CDC, so everything that is not our response is
        skipped. A response can also arrive corrupted (the hub's console
        is lossy under pressure), so idempotent ops get one retry instead
        of surfacing a long hang to the UI.
        """
        if retries is None:
            retries = 1 if _is_idempotent(op_name) else 0
        for attempt in range(retries + 1):
            response = self._op_once(op_name, params, timeout_s)
            if response is not None:
                return response
        raise LinkError("device did not answer op {}".format(op_name))

    def _op_once(self, op_name, params, timeout_s):
        with self._lock:
            request = {"op": op_name, "id": self._next_id}
            self._next_id += 1
            if params is not None:
                request["params"] = params
            line = json.dumps(request) + "\n"
            try:
                self._serial.write(line.encode("utf-8"))
                deadline = time.time() + timeout_s
                while time.time() < deadline:
                    raw = self._serial.readline()
                    if not raw:
                        continue
                    try:
                        response = json.loads(raw.decode("utf-8", "replace"))
                    except ValueError:
                        continue
                    if (isinstance(response, dict) and "ok" in response
                            and response.get("id") == request["id"]):
                        return response
            except (serial.SerialException, OSError) as exc:
                raise LinkError("serial link lost: {}".format(exc))
        return None

    def rest(self, method, path, query, body):
        translated = rest_to_op(method, path, query, body)
        if translated is None:
            return 404, {"ok": False, "error": "not found"}
        op_name, params, created = translated
        response = self.op(op_name, params)
        if response.get("ok"):
            return (201 if created else 200), {"ok": True,
                                               "data": response.get("data")}
        status = _KIND_TO_STATUS.get(response.get("kind"), 500)
        return status, {"ok": False, "error": response.get("error", "error")}


class NetworkLink:
    mode = "network"

    def __init__(self, host, timeout_s=8.0):
        self.host = host
        self._timeout = timeout_s

    def close(self):
        pass

    def describe(self):
        return {"mode": "network", "host": self.host}

    def rest(self, method, path, query, body):
        url = "http://{}{}".format(self.host, path)
        if query:
            url += "?" + urllib.parse.urlencode(
                {k: v[0] for k, v in query.items()})
        data = None
        headers = {}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers,
                                         method=method)
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as res:
                return res.status, json.loads(res.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                return exc.code, json.loads(exc.read().decode("utf-8"))
            except ValueError:
                return exc.code, {"ok": False, "error": "HTTP {}".format(exc.code)}
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise LinkError("network link failed: {}".format(exc))

    def verify(self):
        """Cheap reachability check; raises LinkError when the hub is gone."""
        status, payload = self.rest("GET", "/api/status", {}, None)
        if status != 200 or not payload.get("ok"):
            raise LinkError("hub at {} did not answer /api/status".format(self.host))
