# Smart Kosher — desktop client

Windows app for the hub: a local bridge process plus the product UI in a
native window (pywebview / Edge WebView2).

```
python client/app.py
```

Requires `pyserial` (always) and `pywebview` (for the native window;
without it the UI opens in the default browser).

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
