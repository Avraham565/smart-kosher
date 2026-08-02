# The app store -- the single source of truth. Every screen reads UI state from
# these Signals (via reactive.bind*), and the async producers in main.py write
# them (the clock ticker, the status poll, the H2 reader). Change a Signal in one
# place and every bound widget on every screen updates itself.
#
# Keep values immutable-ish: replace a dict/tuple rather than mutating it in
# place, so Signal.set can skip no-op writes (a mutated container compares equal).
#
# Pure Python (no LVGL) -- testable on CPython.

import asyncio

from reactive import Signal

# ── clock / date ────────────────────────────────────────────────────────────
now = Signal(None)          # (hour, minute) local, or None until the RTC is set
today = Signal(None)        # today.get result dict, or None

# ── hub / brain ─────────────────────────────────────────────────────────────
hub_online = Signal(False)  # brain reachable (status.get succeeded)
app_version = Signal("")
clock_unset = Signal(True)  # RTC still at factory 2000

# ── H2 / zigbee ─────────────────────────────────────────────────────────────
h2_link = Signal(None)      # True up / False down / None unknown

# ── rooms / devices ─────────────────────────────────────────────────────────
devices = Signal({})        # ieee -> {"on_off": bool|None, "unreachable", "endpoint"}
endpoints = Signal([])      # the user's named endpoint entities (device_type)
zones = Signal([])          # the user's rooms
groups = Signal([])         # named cross-room device sets (schedule targets)
schedules = Signal([])      # automations
pairing = Signal(None)      # zone_id being paired into (permit_join window), or None

# ── transient user notification (errors / confirmations) ────────────────────
toast = Signal("")

# ── app context ─────────────────────────────────────────────────────────────
# The composed brain Api, set once at boot. Screens that dispatch (house/settime)
# read it here instead of threading it through every builder.
api = None


def set_api(value):
    global api
    api = value

# ── refresh nudge ───────────────────────────────────────────────────────────
# Lets a writer (e.g. after time.set) ask the clock ticker to refresh now instead
# of waiting for its next poll. The ticker waits on this event with a timeout.
_refresh_event = None


def refresh_event():
    global _refresh_event
    if _refresh_event is None:
        _refresh_event = asyncio.Event()
    return _refresh_event


def request_refresh():
    refresh_event().set()
