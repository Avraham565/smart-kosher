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
_SENTINEL_PERIOD_S = 30

# Backoff for a UART that keeps failing: first pause, then doubling to a cap.
_READER_BACKOFF_S = 0.1
_READER_BACKOFF_MAX_S = 5

# The boot sentinel, printed once the loop is up. host/clean_board.py resets the
# board and greps the boot output for exactly this string, to tell "main.py is
# gone" from "main.py ran again, and the RGB DMA is live" -- and a file copy onto
# a board with live DMA corrupts the VFS. Nothing links the two files: this one
# only ever runs on the device, that one only on the host, so neither can import
# the other. tests/test_boot_sentinel_is_in_sync.py pins them together.
BOOT_SENTINEL = "panel up"

# Link to the H2 coordinator, proven on this exact board in
# tools/zigbee_probe/s3_ui_probe.py: UART1 TX=GPIO5 RX=GPIO19 @115200, no
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
    """Publish live device state and the entity list into the store, so the
    House page renders and toggles reactively.

    It used to adopt the first unclaimed device by itself while pairing, which
    is why the add screen exists and why that is gone: a grab that happens
    before the user has chosen anything makes a two-gang switch one entity
    named after a count, and leaves nothing for a list to show.
    """
    while True:
        try:
            raw = await api.dispatch("zigbee.devices")
            # Keep only stable fields so unchanged polls skip the repaint
            # (state_age_ms would differ every call).
            devices = {}
            for ieee, entry in raw.items():
                devices[ieee] = {
                    "on_off": entry.get("on_off"),
                    "unreachable": bool(entry.get("unreachable")),
                    "endpoint": entry.get("endpoint", 1),
                    # The add screen derives one row per gang from these two,
                    # and cannot without them. Both are stable -- they change
                    # on discovery, not on every poll -- so the repaint-skip
                    # this dict exists for still holds.
                    "endpoints": entry.get("endpoints"),
                    "clusters": entry.get("clusters"),
                    "endpoint_on_off": entry.get("endpoint_on_off"),
                    # Why a device the user just deleted is on the add list.
                    "leave_failed": entry.get("leave_failed"),
                }
            store.devices.set(devices)
            endpoints = await api.dispatch("endpoints.list")
            store.endpoints.set(endpoints)
            store.zones.set(await api.dispatch("zones.list"))
            store.groups.set(await api.dispatch("groups.list"))
            store.schedules.set(await api.dispatch("schedules.list"))
        except Exception as exc:
            print("devices refresh error:", exc)
        await asyncio.sleep(_DEVICES_PERIOD_S)


async def _zigbee_reader(gateway, uart):
    """Event-driven inbound path: wakes the moment a byte arrives (no polling).
    Every line (ack, error, device_joined, attribute_report) goes through
    process_line, which resolves pending commands and heals the registry."""
    reader = asyncio.StreamReader(uart)
    delay = 0
    while True:
        try:
            line = await reader.readline()
            if line:
                gateway.process_line(line)
            delay = 0
        except Exception as exc:
            # readline() is inside the try, not just process_line: it is the
            # call that touches the UART, and a raise here used to escape into
            # the gather and end main() -- leaving the RGB DMA still scanning
            # out a frozen frame (host/clean_board.py), a board that looks
            # alive and is dead.
            print("zigbee line error:", exc)
            # Two separate reasons this backs off rather than retrying flat out.
            # A UART that faults on every read would spin this loop without
            # ever yielding, and on one cooperative loop that starves LVGL and
            # the scheduler too -- the same freeze by another door. And an
            # unthrottled error print is ten lines a second forever, which
            # drowns the sentinel below and makes the console useless for
            # exactly the diagnosis it exists for.
            delay = (min(delay * 2, _READER_BACKOFF_MAX_S) if delay
                     else _READER_BACKOFF_S)
            await asyncio.sleep(delay)


async def _sentinel(tasks):
    """Periodic proof of life on the console. Nothing else can give one.

    BOOT_SENTINEL says the panel started. Until now nothing said it was still
    going, and the two are not the same question: the RGB DMA keeps scanning
    out the last frame whatever the software does (host/clean_board.py), so
    what you see on the glass is evidence of nothing. From outside, a frozen
    panel and a healthy one are identical.

    gather cannot fill the gap either. With return_exceptions it reports only
    once *every* task has ended, and these are infinite loops, so a task that
    dies is silent for as long as the board stays powered.

    Two signals, because there are two ways to stop:

    * ``Task.done()`` names a task that ended -- the failure the guards in
      _zigbee_reader and watchdog make unlikely rather than impossible.
    * the pump's cycle count catches wedging, which done() cannot see: a task
      blocked forever is still 'running'. The pump is the right probe because
      everything shares its one cooperative loop, so a count that stops means
      the loop stopped, whoever actually jammed it.

    What it does not catch, and cannot: this task rides the same cooperative
    loop it is watching. Three ways for the panel to stop, and it sees two.

      * a task that raised and ended        -> done() names it
      * a stall the loop recovers from      -> the cycle count dips, and the
                                               line after it says so
      * the loop blocked for good           -> nothing is reported, because
                                               the reporter is blocked too

    The third is the one a reader will assume is covered, so it is written
    down. Catching it needs a watcher that does not share this loop -- the
    hardware WDT, or the H2 noticing the panel stopped talking to it -- and
    that is separate work, not a bigger version of this.

    Cheap on purpose: one line every _SENTINEL_PERIOD_S, two integers, no
    allocation per cycle anywhere on the hot path.
    """
    last = lvgl_loop.beats
    while True:
        await asyncio.sleep(_SENTINEL_PERIOD_S)
        try:
            cycles = lvgl_loop.beats - last
            last = lvgl_loop.beats
            dead = []
            for name, task in tasks:
                try:
                    if task.done():
                        dead.append(name)
                except AttributeError:
                    # An asyncio build without Task.done still gets the pump
                    # count, which is the half that matters more.
                    break
            print("panel alive:", cycles, "lvgl cycles in",
                  _SENTINEL_PERIOD_S, "s; dead tasks:",
                  ", ".join(dead) if dead else "none")
        except Exception as exc:
            # The liveness probe must never be the thing that dies.
            print("sentinel error:", exc)


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
    print(BOOT_SENTINEL, "— LVGL", lv.version_major(), lv.version_minor(),
          "@", display.PCLK_HZ // 1_000_000,
          "MHz; brain in-process; H2 on UART", _ZIGBEE_UART_ID,
          "; scheduler every", scheduler.TICK_SECONDS, "s")
    watched = (("lvgl pump", pump), ("status", status), ("clock", clockt),
               ("devices", devicest), ("zigbee reader", reader),
               ("zigbee watchdog", heart), ("scheduler", sched))
    # _sentinel is what actually reports a death, every 30s. gather is only the
    # containment: without return_exceptions the first raise unwinds through it,
    # main() returns, and the RGB DMA keeps scanning out the last frame forever
    # -- a wall panel showing rooms and buttons that answers nothing. With it,
    # the others keep running. It reports nothing useful on its own, because it
    # returns only once *all* of these have ended and they are infinite loops:
    # this print is the shutdown record, not the alarm. Held in gather rather
    # than fire-and-forget so the sentinel keeps a live reference (CLAUDE.md).
    alive = asyncio.create_task(_sentinel(watched))
    results = await asyncio.gather(pump, status, clockt, devicest, reader,
                                   heart, sched, alive, return_exceptions=True)
    for (name, _), result in zip(watched + (("sentinel", alive),), results):
        print("panel task ended:", name, "-", result)


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
