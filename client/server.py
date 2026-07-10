"""Local bridge server — serves the UI and relays /api/* to the hub.

Runs on 127.0.0.1 only. Endpoints:
  /                UI (index.html, /static/* assets)
  /api/*           relayed to the hub over the active link
  /bridge/status   GET  — link state (+ lazy serial autoconnect)
  /bridge/ports    GET  — candidate COM ports
  /bridge/connect  POST — {"mode": "serial", "port"?} / {"mode": "network", "host"}
  /bridge/provision POST — {"ssid", "password"} (serial only)
  /bridge/reboot   POST — reboot the hub (serial only)
  /bridge/time_sync POST — set the hub clock from this PC's UTC time
"""

import json
import os
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from bridge import LinkError, NetworkLink, SerialLink, find_device_ports

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
}


class Manager:
    """Owns the active link; all mutations go through one lock."""

    def __init__(self):
        self._link = None
        self._lock = threading.Lock()
        self._last_serial_attempt = 0.0

    def link(self):
        return self._link

    def connect_serial(self, port=None):
        with self._lock:
            candidates = [port] if port else find_device_ports()
            if not candidates:
                raise LinkError("no device on USB")
            self._replace(SerialLink(candidates[0]))
            return self._link.describe()

    def connect_network(self, host):
        with self._lock:
            link = NetworkLink(host)
            link.verify()
            self._replace(link)
            return self._link.describe()

    def disconnect(self):
        with self._lock:
            self._replace(None)

    def _replace(self, link):
        if self._link is not None:
            self._link.close()
        self._link = link

    def status(self):
        """Current state; opportunistically reconnects over USB when idle.

        The serial port drops on every hub reboot (USB re-enumerates), so
        the UI's status poll doubles as the auto-reconnect loop — at most
        one attempt per 3 seconds to keep the poll cheap.
        """
        link = self._link
        if link is None and time.time() - self._last_serial_attempt > 3.0:
            self._last_serial_attempt = time.time()
            try:
                self.connect_serial()
                link = self._link
            except LinkError:
                link = None
        if link is None:
            return {"connected": False}
        info = {"connected": True}
        info.update(link.describe())
        return info


def _pc_utc_fields():
    now = time.gmtime()
    return {"year": now.tm_year, "month": now.tm_mon, "day": now.tm_mday,
            "hour": now.tm_hour, "minute": now.tm_min, "second": now.tm_sec}


class BridgeHandler(BaseHTTPRequestHandler):
    # set by serve(): manager, ui_dir

    def log_message(self, fmt, *args):
        pass  # keep the console clean; errors surface as HTTP responses

    # ── plumbing ──────────────────────────────────────────────────────────────

    def _send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length == 0:
            return None
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except ValueError:
            return None

    def _serve_ui(self, path):
        name = "index.html" if path == "/" else path[len("/static/"):]
        # Subdirectories are allowed (the UI ships as js/ modules); path
        # traversal and absolute paths are not.
        if "\\" in name or ".." in name or name.startswith("/") or not name:
            return self._send_json(404, {"ok": False, "error": "not found"})
        full = os.path.realpath(os.path.join(self.server.ui_dir, name))
        root = os.path.realpath(self.server.ui_dir)
        if not full.startswith(root + os.sep):
            return self._send_json(404, {"ok": False, "error": "not found"})
        ext = "." + name.rsplit(".", 1)[-1]
        try:
            with open(full, "rb") as f:
                body = f.read()
        except OSError:
            return self._send_json(404, {"ok": False, "error": "not found"})
        self.send_response(200)
        self.send_header("Content-Type",
                         _CONTENT_TYPES.get(ext, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ── request routing ───────────────────────────────────────────────────────

    def _handle(self, method):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)
        manager = self.server.manager

        try:
            if method == "GET" and (path == "/" or path.startswith("/static/")):
                return self._serve_ui(path)

            if path.startswith("/api/"):
                link = manager.link()
                if link is None:
                    return self._send_json(
                        503, {"ok": False, "error": "המכשיר אינו מחובר"})
                body = self._read_body() if method in ("POST", "PUT", "PATCH") else None
                try:
                    status, payload = link.rest(method, path, query, body)
                except LinkError as exc:
                    manager.disconnect()
                    return self._send_json(502, {"ok": False, "error": str(exc)})
                return self._send_json(status, payload)

            if path == "/bridge/status" and method == "GET":
                return self._send_json(200, {"ok": True, "data": manager.status()})

            if path == "/bridge/ports" and method == "GET":
                return self._send_json(
                    200, {"ok": True, "data": find_device_ports()})

            if path == "/bridge/connect" and method == "POST":
                body = self._read_body() or {}
                mode = body.get("mode")
                try:
                    if mode == "serial":
                        info = manager.connect_serial(body.get("port"))
                    elif mode == "network":
                        host = (body.get("host") or "").strip()
                        if not host:
                            return self._send_json(
                                400, {"ok": False, "error": "נא להזין כתובת"})
                        info = manager.connect_network(host)
                    else:
                        return self._send_json(
                            400, {"ok": False, "error": "mode must be serial or network"})
                except LinkError as exc:
                    return self._send_json(502, {"ok": False, "error": str(exc)})
                return self._send_json(200, {"ok": True, "data": info})

            if path == "/bridge/provision" and method == "POST":
                link = manager.link()
                if link is None or link.mode != "serial":
                    return self._send_json(400, {
                        "ok": False,
                        "error": "הגדרת רשת אפשרית רק בחיבור USB"})
                body = self._read_body() or {}
                try:
                    response = link.op("wifi.provision", {
                        "ssid": body.get("ssid"),
                        "password": body.get("password"),
                    })
                except LinkError as exc:
                    manager.disconnect()
                    return self._send_json(502, {"ok": False, "error": str(exc)})
                if not response.get("ok"):
                    return self._send_json(
                        400, {"ok": False, "error": response.get("error")})
                return self._send_json(200, {"ok": True, "data": response.get("data")})

            if path == "/bridge/reboot" and method == "POST":
                link = manager.link()
                if link is None or link.mode != "serial":
                    return self._send_json(400, {
                        "ok": False, "error": "אתחול מרחוק אפשרי רק בחיבור USB"})
                try:
                    link.op("system.reboot")
                except LinkError:
                    pass  # USB drops mid-reboot; that is the point
                manager.disconnect()
                return self._send_json(200, {"ok": True, "data": {"rebooting": True}})

            if path == "/bridge/time_sync" and method == "POST":
                link = manager.link()
                if link is None:
                    return self._send_json(
                        503, {"ok": False, "error": "המכשיר אינו מחובר"})
                try:
                    status, payload = link.rest(
                        "POST", "/api/time", {}, _pc_utc_fields())
                except LinkError as exc:
                    manager.disconnect()
                    return self._send_json(502, {"ok": False, "error": str(exc)})
                return self._send_json(status, payload)

            return self._send_json(404, {"ok": False, "error": "not found"})
        except Exception as exc:
            return self._send_json(500, {"ok": False, "error": str(exc)})

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_PUT(self):
        self._handle("PUT")

    def do_PATCH(self):
        self._handle("PATCH")

    def do_DELETE(self):
        self._handle("DELETE")


def serve(manager, ui_dir, port=0):
    """Start the bridge server on 127.0.0.1; returns (server, actual_port)."""
    httpd = ThreadingHTTPServer(("127.0.0.1", port), BridgeHandler)
    httpd.manager = manager
    httpd.ui_dir = ui_dir
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, httpd.server_address[1]
