# Product A entry point -- the CrowPanel runs the UI, the brain, and the H2
# Zigbee coordinator link together in one MicroPython process, on one asyncio
# loop.
#
# Boot order (each step depends on the previous):
#   1) display.init()       RGB panel (bounce-equivalent PARTIAL buffers) + touch
#   2) theme.load_fonts()   binfont_create needs the VFS + an initialised LVGL
#   3) repo + H2 gateway    JSON storage + the real ZigbeeGateway over UART1
#   4) brain.create()       compose the in-process Api around them
#   5) ui_home.create(api)  build the static home face; sub-screens dispatch to
#                           the brain (clock set writes time.set)
#   6) asyncio.run(_run)    own the LVGL pump + brain + H2 tasks on ONE loop
#
# LVGL is pumped from the loop (lvgl_loop.py), NOT from task_handler.TaskHandler,
# so LVGL, the brain, and the H2 reader/watchdog share a single cooperative
# context and never race. Rendering-stability rules this file must never break
# (see memory panel-mp-rendering): no gc.collect()/gc.threshold() once rendering
# has started, no full-screen animation, no scrolling.

import asyncio
import time

import lvgl as lv

import brain
import display
import lvgl_loop
import store
import theme
import toast
import uart_tap
import ui_home
from smart_kosher.application import scheduler
from smart_kosher.ports.clock import MIN_VALID_YEAR

_STATUS_PERIOD_S = 5
_CLOCK_PERIOD_S = 10
_DEVICES_PERIOD_S = 3

# Link to the H2 coordinator, proven on this exact board in
# experiments/zigbee_probe (s3_ui_probe): UART1 TX=GPIO5 RX=GPIO19 @115200, no
# conflict with the RGB display pins. Driven event-driven here (StreamReader),
# not polled from an LVGL timer as the probe did -- we own the asyncio loop.
_ZIGBEE_UART_ID = 1
_ZIGBEE_TX_PIN = 5
_ZIGBEE_RX_PIN = 19
_ZIGBEE_BAUD = 115200
# 1024 bytes is only ~89ms of wire at this baud. Everything on this board --
# LVGL, the brain, the scheduler -- shares one cooperative loop, and any block
# longer than that drops inbound H2 frames (a device_joined or an
# attribute_report, lost with no error anywhere). The scheduler's first tick
# computes a week of zmanim in one uninterruptible go, which is exactly such a
# block. 4096 buys ~355ms of slack; PSRAM makes the cost irrelevant.
_ZIGBEE_RXBUF = 4096


def _make_zigbee(repo):
    from machine import UART

    from smart_kosher.adapters import ZigbeeGateway
    uart = UART(_ZIGBEE_UART_ID, baudrate=_ZIGBEE_BAUD,
                tx=_ZIGBEE_TX_PIN, rx=_ZIGBEE_RX_PIN, timeout=0,
                rxbuf=_ZIGBEE_RXBUF)
    gateway = ZigbeeGateway(
        uart, repo, registry_path=brain.DATA_DIR + "/zigbee_devices.json")
    return gateway, uart


async def _status_refresh(api):
    """Poll status.get and publish the brain/H2 state into the store; the home
    footer is bound to these Signals and re-renders itself. Cheap (no zmanim)."""
    while True:
        try:
            data = await api.dispatch("status.get")
            store.hub_online.set(True)
            store.app_version.set(data.get("app_version", ""))
            store.clock_unset.set(bool(data.get("clock_unset")))
            if data.get("link_down"):
                store.h2_link.set(False)
            elif data.get("network_up"):
                store.h2_link.set(True)
            else:
                store.h2_link.set(None)
        except Exception:
            store.hub_online.set(False)
        await asyncio.sleep(_STATUS_PERIOD_S)


async def _clock_refresh(api):
    """Drive the home clock from the RTC + brain. The RTC holds UTC; today.get
    supplies the DST-correct offset and the Hebrew/Gregorian date. Until the RTC
    is set (fresh boot reads year 2000) the header prompts for it. Refreshes on a
    timer, or immediately when clock.request_refresh() fires (after a set)."""
    event = store.refresh_event()
    while True:
        try:
            now = time.localtime()
            if now[0] < MIN_VALID_YEAR:
                store.now.set(None)
                store.today.set(None)
            else:
                today = await api.dispatch("today.get")
                offset = today.get("utc_offset_minutes", 0)
                total = (now[3] * 60 + now[4] + offset) % 1440
                store.now.set((total // 60, total % 60))
                store.today.set(today)
        except Exception as exc:
            print("clock refresh error:", exc)
        try:
            await asyncio.wait_for(event.wait(), _CLOCK_PERIOD_S)
        except asyncio.TimeoutError:
            pass
        event.clear()


async def _devices_refresh(api):
    """Publish live device state (from the gateway registry) and the endpoint
    list into the store, so the House page renders/toggles reactively. While
    pairing, auto-adopt the first joined device that is not yet an endpoint."""
    while True:
        try:
            raw = await api.dispatch("zigbee.devices")
            # Keep only stable fields so unchanged polls skip the repaint
            # (state_age_ms would differ every call).
            devices = {}
            for ieee, entry in raw.items():
                devices[ieee] = {"on_off": entry.get("on_off"),
                                 "unreachable": bool(entry.get("unreachable")),
                                 "endpoint": entry.get("endpoint", 1)}
            store.devices.set(devices)
            endpoints = await api.dispatch("endpoints.list")
            store.endpoints.set(endpoints)
            store.zones.set(await api.dispatch("zones.list"))
            store.groups.set(await api.dispatch("groups.list"))
            store.schedules.set(await api.dispatch("schedules.list"))
            if store.pairing.get() is not None:
                await _try_autopair(api, devices, endpoints)
        except Exception as exc:
            print("devices refresh error:", exc)
        await asyncio.sleep(_DEVICES_PERIOD_S)


async def _try_autopair(api, devices, endpoints):
    zone_id = store.pairing.get()
    linked = set(ep.get("ieee_address") for ep in endpoints)
    for ieee, entry in devices.items():
        if ieee and ieee not in linked:
            data = {"name": "מכשיר {}".format(len(endpoints) + 1),
                    "ieee_address": ieee,
                    "zigbee_endpoint": entry.get("endpoint", 1)}
            if zone_id:
                data["zone_id"] = zone_id
            await api.dispatch("endpoints.create", {"data": data})
            store.pairing.set(None)
            store.endpoints.set(await api.dispatch("endpoints.list"))
            print("paired new device:", ieee, "-> zone", zone_id)
            break


async def _zigbee_reader(gateway, uart):
    """Event-driven inbound path: wakes the moment a byte arrives (no polling).
    Every line (ack, error, device_joined, attribute_report) goes through
    process_line, which resolves pending commands and heals the registry."""
    reader = asyncio.StreamReader(uart)
    while True:
        line = await reader.readline()
        if line:
            try:
                gateway.process_line(line)
            except Exception as exc:
                print("zigbee line error:", exc)


async def _run(composed, gateway, uart):
    pump = asyncio.create_task(lvgl_loop.pump())
    status = asyncio.create_task(_status_refresh(composed.api))
    clockt = asyncio.create_task(_clock_refresh(composed.api))
    devicest = asyncio.create_task(_devices_refresh(composed.api))
    reader = asyncio.create_task(_zigbee_reader(gateway, uart))
    heart = asyncio.create_task(gateway.watchdog())
    # What turns a saved schedule into a sent command. Its first tick also does
    # boot catch-up, so a schedule missed while the panel was powered off still
    # fires (bounded look-back + journal dedup -- see scheduler.py).
    sched = asyncio.create_task(scheduler.Scheduler.for_brain(composed).run())
    print("panel_mp up — LVGL", lv.version_major(), lv.version_minor(),
          "@", display.PCLK_HZ // 1_000_000,
          "MHz; brain in-process; H2 on UART", _ZIGBEE_UART_ID,
          "; scheduler every", scheduler.TICK_SECONDS, "s")
    await asyncio.gather(pump, status, clockt, devicest, reader, heart, sched)


def main():
    from smart_kosher.adapters.json_repository import JsonRepository
    display.init()
    theme.load_fonts()
    repo = JsonRepository(brain.DATA_DIR)
    gateway, uart = _make_zigbee(repo)
    # Opt-in wire log for bench diagnosis: create /data/uart_tap to have every
    # H2 frame printed to the console, delete it to go quiet. See uart_tap.py.
    uart_tap.maybe_install(gateway, brain.DATA_DIR + "/uart_tap")

    # Battery-backed RTC (PCF8563 @0x51 on the display I2C bus): restore the
    # system clock from it at boot so a set time survives power-off, and let the
    # brain write both the chip and the ESP32 RTC on time.set.
    from smart_kosher.adapters.pcf8563 import PCF8563
    rtc = PCF8563(display.i2c)
    print("RTC restored from PCF8563" if rtc.sync_to_system()
          else "PCF8563 has no set time yet")

    composed = brain.create(repository=repo, gateway=gateway, zigbee=True,
                            clock=rtc)
    store.set_api(composed.api)
    ui_home.create(composed.api)
    toast.install()
    asyncio.run(_run(composed, gateway, uart))


main()
