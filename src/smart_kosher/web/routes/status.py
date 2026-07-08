"""Route for /api/status — hub health for the UI header and diagnostics."""

import gc
import time

from ..responses import ok

APP_VERSION = "0.1.0"


def _memory_info():
    """Free/used heap bytes on MicroPython; None under CPython."""
    mem_free = getattr(gc, "mem_free", None)
    if mem_free is None:
        return None
    info = {"free": mem_free()}
    mem_alloc = getattr(gc, "mem_alloc", None)
    if mem_alloc is not None:
        info["allocated"] = mem_alloc()
    return info


def register(app, settings_store, extra_info=None):
    started = time.time()

    @app.get("/api/status")
    async def get_status(req):
        now = time.localtime()
        data = {
            "app_version": APP_VERSION,
            "device_time": "{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}".format(
                now[0], now[1], now[2], now[3], now[4], now[5]
            ),
            "uptime_seconds": int(time.time() - started),
            "settings_load_error": getattr(settings_store, "load_error", None),
            "memory": _memory_info(),
            # A fresh MicroPython boot reads 2000-01-01 until the RTC is set.
            "clock_unset": now[0] < 2013,
        }
        if extra_info is not None:
            try:
                info = extra_info() if callable(extra_info) else extra_info
                if isinstance(info, dict):
                    data.update(info)
            except Exception as exc:
                data["extra_info_error"] = str(exc)
        return ok(data)
