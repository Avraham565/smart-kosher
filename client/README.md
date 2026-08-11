# Smart Kosher — desktop client

> **Status: paused (2026-08-05).** This is the client for **product B**, the
> headless AtomS3 hub, which is not being worked on right now. Product A (the
> wall panel) is its own client and does not use this. See the repo README.
> Note that product B currently never fires schedules — see
> `deploy/atoms3/main.py`.

Windows app for the hub: a local bridge process plus the product UI in a
native window (pywebview / Edge WebView2).

```
python client/app.py
```

Requires `pyserial` (always) and `pywebview` (for the native window;
without it the UI opens in the default browser).

## Building the exe

```
powershell -ExecutionPolicy Bypass -File client\build.ps1
```

Produces `client\dist\SmartKosher.exe` (one file, no console; needs the
repo venv with `pyinstaller` installed). Flags useful for testing:
`SmartKosher.exe --port 18765 --no-window` runs the bridge headless on a
fixed port.

## How it works

- `bridge.py` — device links. `SerialLink` speaks the hub's op protocol
  over USB CDC (one JSON per line) and translates the UI's REST calls to
  ops; `NetworkLink` forwards REST to the hub's HTTP server on the home
  network.
- `server.py` — local HTTP server on 127.0.0.1: serves `ui/`, relays
  `/api/*` over the active link, and exposes `/bridge/*` for
  desktop-only actions: connect, WiFi provisioning, reboot, and time
  sync (sends the PC clock as **UTC** — the hub's RTC holds UTC).
- `app.py` — entry point; auto-connects over USB when the hub is
  plugged in.
- `ui/` — the product web UI (Hebrew, RTL). It is the same UI that once
  ran on the device; it moved here because the hub is API-only.

The serial port drops on every hub reboot; the bridge auto-reconnects
during the UI's status polling (at most one attempt per 3 seconds).
