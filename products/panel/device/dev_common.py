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


def device_state(ieee):
    """(text, color) for a device's live state, from store.devices."""
    device = store.devices.get().get(ieee) if ieee else None
    if device is None:
        return "—", theme.FAINT
    if device.get("unreachable"):
        return "לא זמין", theme.DANGER
    on = device.get("on_off")
    if on is None:
        return "—", theme.FAINT
    return ("דלוק", theme.SUCCESS) if on else ("כבוי", theme.MUTED)


def device_toggle(ep_id, ieee):
    """Flip a device: optimistic store update (instant UI) + control.send.

    The optimistic write stays, unlike the other write paths on this panel: a
    radio command takes real time, and a switch that does not light up until
    the relay answers feels broken even when it works. But an optimistic write
    is a guess, and a guess that is never withdrawn is worse than no guess --
    the panel would show the light on for the three seconds until the device
    poll corrected it, which reads as "the panel is lying", not "the command
    failed".
    """
    if not ieee:
        return                                   # not paired -> nothing to toggle
    device = store.devices.get().get(ieee)
    current = device.get("on_off") if device else None
    action = "off" if current else "on"
    wanted = (action == "on")
    devices = dict(store.devices.get())
    entry = dict(devices.get(ieee) or {})
    entry["on_off"] = wanted
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
        if held is not None and held.get("on_off") == wanted:
            restored = dict(held)
            restored["on_off"] = current
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
                    {"target_type": "endpoint", "target_id": ep_id,
                     "action_type": action},
                    on_ok=ok,
                    on_err=lambda kind, message: withdraw("שגיאה בשליחת הפקודה"))
