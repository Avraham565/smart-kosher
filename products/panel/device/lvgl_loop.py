# The LVGL pump, owned by the asyncio loop.
#
# Why not task_handler.TaskHandler (which the earlier UI-only probes used)? That
# helper drives LVGL from MicroPython's *internal* scheduler -- a different
# execution context from asyncio (see experiments s3_ui_probe.py: "TaskHandler
# drives LVGL refresh via MicroPython internal scheduler"). The brain is
# asyncio-native: Api.dispatch is a coroutine, and the Zigbee reader/watchdog are
# tasks. Two contexts both touching LVGL would race -- LVGL is not re-entrant or
# thread-safe. So we drive LVGL here, from one asyncio task, and run everything
# -- rendering, the brain, and UI event callbacks -- on that single cooperative
# loop. No locks, no cross-context handoff.
#
# LVGL v9 (9.2.2): ``lv.timer_handler()`` services timers + rendering and
# ``lv.tick_inc(ms)`` advances LVGL's clock. TaskHandler did both internally; we
# do them explicitly. (``lv.task_handler`` is the pre-v9 name -- kept only as a
# fallback for a build that still exposes that alias.)
#
# This module is hardware-only (imports lvgl); it never runs on CPython.

import asyncio
import time

import lvgl as lv

# The sleep is 5ms but a cycle costs ~10ms: _handler() itself takes about as
# long again, so LVGL is serviced ~99.6x/s on the board -- not the ~200 the
# interval alone implies, which is true only for an instant handler. Measured,
# with the arithmetic: docs/panel-update-model.md. Still negligible against a
# ~51 Hz frame, and near-free at idle (the await yields the core between
# cycles).
_PUMP_INTERVAL_MS = 5

_handler = getattr(lv, "timer_handler", None) or getattr(lv, "task_handler", None)

# Cycles completed, read by main.py's sentinel as the panel's proof of life.
# This pump is the one whose death is invisible: the RGB DMA keeps scanning out
# the last frame whatever the software does (host/clean_board.py), so a frozen
# count is the only symptom a wedged UI has. A plain counter, deliberately --
# no timestamp, no history, nothing that allocates per cycle at ~100 Hz.
beats = 0


async def pump():
    """Service LVGL forever from the asyncio loop: advance the tick from the
    monotonic clock, then run the timer/render handler each cycle."""
    global beats
    if _handler is None:
        raise RuntimeError(
            "LVGL binding exposes neither timer_handler nor task_handler")
    last = time.ticks_ms()
    while True:
        now = time.ticks_ms()
        elapsed = time.ticks_diff(now, last)
        last = now
        if elapsed > 0:
            lv.tick_inc(elapsed)
        _handler()
        beats += 1
        await asyncio.sleep_ms(_PUMP_INTERVAL_MS)
