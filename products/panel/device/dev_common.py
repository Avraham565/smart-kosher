# Shared device helpers used by the room list and the device page: the live
# on/off label (bound via store.devices) and the optimistic toggle.
#
# (This header used to claim "no LVGL, so it is testable". It was already
# untrue -- theme imports lvgl, and has since this module was written -- so
# importing toast below costs nothing that was not already spent.)

import bridge
import store
import theme
import toast

# Which fields belong to the radio and which to one relay on it. Stated here
# because the two live in the same dict and the difference is invisible at the
# call site: unreachable is true of the whole device and both gangs should show
# it; on_off never is. Z2M keeps a multiEndpointSkip list for exactly this, and
# gets it wrong when a field lands on the wrong side of it.
#
#   device-wide : short_addr, endpoint, endpoints, clusters,
#                 unreachable, reporting_error, leave_failed
#   per gang    : on_off, state_age_ms
_PER_GANG_FIELDS = ("on_off", "state_age_ms")


def _gang_state(entity):
    """This entity's own on/off, or None. Never the device's, never a neighbour's.

    Takes the entity rather than (ieee, endpoint) deliberately. The obvious
    shape -- a lookup keyed by endpoint into a device-level map -- is the
    Zigbee2MQTT model: one shared blob with a discriminator applied at read
    time, where a missing key falls back to the shared value silently. That is
    where their whole family of cross-gang bugs lives
    (docs/multi-endpoint-state.md). Here there is simply no code path that can
    return a device-level answer.
    """
    ieee = entity.get("ieee_address") if entity else None
    if not ieee:
        return None
    device = store.devices.get().get(ieee)
    if device is None:
        return None
    endpoint = entity.get("zigbee_endpoint", 1)
    per_gang = device.get("endpoint_on_off") or {}
    if endpoint in per_gang:
        return per_gang[endpoint]
    # No entry for this gang. On a device we know has more than one, that is
    # an answer of its own -- borrowing the device-level value would hand gang
    # 1 whatever gang 2 last did. "I don't know" beats a neighbour's state.
    gangs = device.get("endpoints") or []
    clusters = device.get("clusters") or {}
    onoff = [ep for ep in gangs if 6 in (clusters.get(str(ep)) or [])]
    if len(onoff) > 1:
        return None
    return device.get("on_off")


def device_state(entity):
    """(text, color) for one endpoint entity's live state."""
    ieee = entity.get("ieee_address") if entity else None
    device = store.devices.get().get(ieee) if ieee else None
    if device is None:
        return "—", theme.FAINT
    # Device-wide: true of the radio, so every gang on it shows it.
    if device.get("unreachable"):
        return "לא זמין", theme.DANGER
    on = _gang_state(entity)
    if on is None:
        return "—", theme.FAINT
    return ("דלוק", theme.SUCCESS) if on else ("כבוי", theme.MUTED)


def device_toggle(entity):
    """Flip a device: optimistic store update (instant UI) + control.send.

    The optimistic write stays, unlike the other write paths on this panel: a
    radio command takes real time, and a switch that does not light up until
    the relay answers feels broken even when it works. But an optimistic write
    is a guess, and a guess that is never withdrawn is worse than no guess --
    the panel would show the light on for the three seconds until the device
    poll corrected it, which reads as "the panel is lying", not "the command
    failed".
    """
    ieee = entity.get("ieee_address") if entity else None
    if not ieee:
        return                                   # not paired -> nothing to toggle
    endpoint = entity.get("zigbee_endpoint", 1)
    current = _gang_state(entity)
    action = "off" if current else "on"
    wanted = (action == "on")
    # The guess goes in this gang's cell. Written device-wide it lit both rows
    # of a two-gang switch on every tap, and the poll three seconds later then
    # cleared both -- which is the symptom this task exists to remove.
    devices = dict(store.devices.get())
    entry = dict(devices.get(ieee) or {})
    per_gang = dict(entry.get("endpoint_on_off") or {})
    per_gang[endpoint] = wanted
    entry["endpoint_on_off"] = per_gang
    devices[ieee] = entry
    store.devices.set(devices)

    def withdraw(message):
        # Compare and swap, not a blind restore. An attribute_report may have
        # landed while the command was in flight, and that is the device's own
        # word about itself -- which outranks our guess (CLAUDE.md: _states is
        # the device speaking). Only take the guess back if it is still what
        # is on screen.
        latest = dict(store.devices.get())
        held = latest.get(ieee)
        if held is None:
            toast.notify(message)
            return
        per_gang_now = dict(held.get("endpoint_on_off") or {})
        # Same compare-and-swap, on this gang's cell. The logic is unchanged
        # and deliberately so -- only the cell it reads and writes moved.
        if per_gang_now.get(endpoint) == wanted:
            if current is None:
                per_gang_now.pop(endpoint, None)
            else:
                per_gang_now[endpoint] = current
            restored = dict(held)
            restored["endpoint_on_off"] = per_gang_now
            latest[ieee] = restored
            store.devices.set(latest)
        toast.notify(message)

    def ok(result):
        # A dispatch that succeeded is not a command that worked. The executor
        # returns {"status": "failed"} as a perfectly ordinary value
        # (executor.py) rather than raising, so no ApiError is ever produced
        # and on_err never fires -- the real answer arrives here.
        #
        # Only "failed" is a failure: "ack_unjournaled" means the device did
        # act and only the journal write did not, so the light really is on.
        if (result or {}).get("status") == "failed":
            withdraw("הפקודה לא הגיעה למכשיר")

    bridge.dispatch(store.api, "control.send",
                    {"target_type": "endpoint", "target_id": entity["id"],
                     "action_type": action},
                    on_ok=ok,
                    on_err=lambda kind, message: withdraw("שגיאה בשליחת הפקודה"))
