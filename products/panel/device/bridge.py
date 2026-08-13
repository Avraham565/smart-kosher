# Sync-callback -> async-dispatch bridge.
#
# LVGL event callbacks are synchronous and cannot ``await``. In this build LVGL
# is pumped from the asyncio loop itself (see lvgl_loop.py -- we own
# lv.timer_handler on the loop, there is no task_handler.TaskHandler), so a
# callback runs *inside* a loop iteration and can safely schedule a task.
#
# ``dispatch`` fires an Api op as a background task and marshals the result back
# through plain callbacks. Those callbacks run cooperatively on the same
# single-threaded loop, so touching LVGL from them is race-free: they never run
# concurrently with the pump (no LVGL re-entrancy).
#
# KEEPALIVE: this MicroPython asyncio will garbage-collect a task whose reference
# nobody holds, before it runs (same reason products/hub/device/main.py keeps its
# create_task() handles in locals). A fire-and-forget dispatch from a UI callback
# has no such local, so we pin every in-flight task in ``_pending`` and drop it
# on completion. Without this the op silently never runs.
#
# This module is UI/LVGL-agnostic (pure asyncio + the Api contract), so it is
# unit-testable on CPython.

import asyncio

from smart_kosher.application.api import ApiError

_pending = set()


def dispatch(api, op, params=None, on_ok=None, on_err=None):
    """Fire ``op`` on ``api`` from a synchronous context (e.g. an LVGL event).

    Non-blocking: returns the scheduled task immediately; later, on the loop,
    exactly one of ``on_ok(data)`` / ``on_err(kind, message)`` is invoked. A UI
    action can never crash the loop -- unexpected errors are reported as the
    Api's own ``internal`` kind (and printed for the serial log).
    """
    holder = {}

    async def runner():
        try:
            data = await api.dispatch(op, params)
        except ApiError as exc:
            print("dispatch %s -> %s: %s" % (op, exc.kind, exc))
            if on_err is not None:
                on_err(exc.kind, str(exc))
        except Exception as exc:
            print("dispatch %s failed:" % op, exc)
            if on_err is not None:
                on_err("internal", str(exc))
        else:
            if on_ok is not None:
                on_ok(data)
        finally:
            _pending.discard(holder.get("task"))

    task = asyncio.create_task(runner())
    holder["task"] = task
    _pending.add(task)          # keep alive until runner() finishes
    return task
