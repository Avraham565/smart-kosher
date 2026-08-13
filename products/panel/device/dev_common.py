# Shared device helpers used by the room list and the device page: the live
# on/off label (bound via store.devices) and the optimistic toggle. Pure app
# logic -- no LVGL, so it is testable.

import bridge
import store
import theme


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
    """Flip a device: optimistic store update (instant UI) + control.send."""
    if not ieee:
        return                                   # not paired -> nothing to toggle
    device = store.devices.get().get(ieee)
    current = device.get("on_off") if device else None
    action = "off" if current else "on"
    devices = dict(store.devices.get())
    entry = dict(devices.get(ieee) or {})
    entry["on_off"] = (action == "on")
    devices[ieee] = entry
    store.devices.set(devices)
    bridge.dispatch(store.api, "control.send",
                    {"target_type": "endpoint", "target_id": ep_id,
                     "action_type": action})
