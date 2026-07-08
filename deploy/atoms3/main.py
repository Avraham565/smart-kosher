"""AtomS3 Lite entry point — Smart Kosher headless hub (product B).

Deployed to the device root as /main.py (see deploy.ps1). Runs under
MicroPython v1.24.1.

The hub is API-only and serves two channels off one Api dispatcher:
  - HTTP (Microdot) on the home network — STA credentials come from
    /data/wifi.json
  - line-delimited JSON over the USB CDC — always available, including
    wifi.provision / wifi.status / system.reboot device ops, so a hub
    with no (or wrong) WiFi credentials can always be recovered

There is no AP mode and no on-device UI.

Storage layout on the device:
    /lib/microdot/       Microdot (only __init__.py + microdot.py)
    /lib/smart_kosher/   the product package
    /data/               JSON entities + settings + wifi.json + journal.log
"""

import asyncio
import gc
import json
import time

from smart_kosher import serial_channel
from smart_kosher.adapters import H2Simulator, MachineRtcClock, SettingsStore
from smart_kosher.adapters.json_repository import JsonEventJournal, JsonRepository
from smart_kosher.application.api import Api, ApiError, BAD_REQUEST
from smart_kosher.application.control_service import ControlService
from smart_kosher.application.crud_service import CrudService
from smart_kosher.application.device_time import DeviceTimeService
from smart_kosher.application.executor import Executor
from smart_kosher.application.views import ViewService
from smart_kosher.web.server import create_app

DATA_DIR = "/data"
WIFI_CONFIG = DATA_DIR + "/wifi.json"
WIFI_CONNECT_TIMEOUT_S = 20

# AtomS3 Lite has no PSRAM (~250KB usable heap). The journal keeps every
# record as Python objects in RAM, so keep it small; 64 records still cover
# a two-day catch-up horizon at pilot scale.
JOURNAL_MAX_RECORDS = 64


def connect_wifi():
    """Join the home network with credentials from /data/wifi.json.

    Returns the station IP, or None when the file is missing or the join
    fails — the server still starts so the USB-serial channel can be used
    to (re)provision credentials.
    """
    try:
        with open(WIFI_CONFIG) as f:
            cfg = json.load(f)
        ssid, password = cfg["ssid"], cfg["password"]
    except (OSError, ValueError, KeyError):
        print("no wifi config - waiting for provisioning over USB serial")
        return None

    import network
    sta = network.WLAN(network.STA_IF)
    sta.active(True)
    if not sta.isconnected():
        sta.connect(ssid, password)
        deadline = time.ticks_add(time.ticks_ms(), WIFI_CONNECT_TIMEOUT_S * 1000)
        while not sta.isconnected():
            if time.ticks_diff(deadline, time.ticks_ms()) < 0:
                print("wifi join failed:", ssid)
                return None
            time.sleep_ms(200)
    return sta.ifconfig()[0]


def device_ops():
    """Device-only serial ops: WiFi provisioning and reboot."""

    def wifi_provision(params):
        ssid = params.get("ssid")
        password = params.get("password")
        if not isinstance(ssid, str) or not ssid.strip():
            raise ApiError(BAD_REQUEST, "ssid must be a non-empty string")
        if not isinstance(password, str) or len(password) < 8:
            raise ApiError(BAD_REQUEST,
                           "password must be at least 8 characters (WPA2)")
        with open(WIFI_CONFIG, "w") as f:
            json.dump({"ssid": ssid, "password": password}, f)
        return {"ssid": ssid, "saved": True,
                "note": "send system.reboot to apply"}

    def wifi_status(params):
        import network
        sta = network.WLAN(network.STA_IF)
        connected = sta.active() and sta.isconnected()
        info = {"connected": connected}
        try:
            import os
            os.stat(WIFI_CONFIG)
            info["config_present"] = True
        except OSError:
            info["config_present"] = False
        if connected:
            info["ip"] = sta.ifconfig()[0]
        return info

    def system_reboot(params):
        # Reset after a short delay so the response line reaches the client
        # before USB drops.
        async def _reset_soon():
            await asyncio.sleep(1)
            import machine
            machine.reset()
        asyncio.create_task(_reset_soon())
        return {"rebooting": True}

    return {
        "wifi.provision": wifi_provision,
        "wifi.status": wifi_status,
        "system.reboot": system_reboot,
    }


def main():
    repo     = JsonRepository(DATA_DIR)
    journal  = JsonEventJournal(repo, max_records=JOURNAL_MAX_RECORDS)
    gateway  = H2Simulator()  # replace with the real gateway once NanoC6 is wired
    executor = Executor(gateway, journal)
    crud     = CrudService(repo)
    control  = ControlService(executor, repo)
    settings = SettingsStore(
        DATA_DIR + "/settings.json",
        defaults={
            "city": "ירושלים",
            "lat": 31.7683,
            "lon": 35.2137,
            "utc_offset_minutes": 120,
            "candle_offset": 18,
            "tzais_offset": 40,
            "in_israel": True,
        },
    )

    ip = connect_wifi()

    def status_info():
        return {"gateway": "simulator", "storage": "json"}

    api = Api(
        crud, control, settings,
        views=ViewService(repo),
        device_time=DeviceTimeService(MachineRtcClock()),
        status_info=status_info,
    )
    app = create_app(crud, control, settings, api=api)

    gc.collect()
    # Collect early and often instead of waiting for the heap to fill —
    # on a no-PSRAM board late collection means fragmentation and
    # MemoryError spikes while a request is being served.
    if hasattr(gc, "threshold"):
        gc.threshold(48 * 1024)
    if ip:
        print("Smart Kosher hub API: http://{}/api/status".format(ip))
    print("free heap after boot:", gc.mem_free())

    # No debug=True: HTTP request logging would interleave with the serial
    # channel's JSON lines on the shared USB CDC.
    async def run():
        server = asyncio.create_task(app.start_server(host="0.0.0.0", port=80))
        print("serial channel ready")
        await serial_channel.serve(api, device_ops())

    asyncio.run(run())


try:
    main()
except KeyboardInterrupt:
    # mpremote attached and interrupted us on purpose — drop to the REPL.
    raise
except Exception as exc:
    # If the server ever dies, leave a readable trace on the serial console
    # and reboot into a clean state instead of a half-dead hub that holds
    # the WiFi association but serves nothing.
    import sys
    sys.print_exception(exc)
    print("server crashed - resetting in 5 seconds")
    import time
    time.sleep(5)
    import machine
    machine.reset()
