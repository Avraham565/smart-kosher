# House page -- the user's named devices with live on/off state and tap-to-
# toggle, plus "add device" (Zigbee pairing). Reactive throughout:
#   * the row list rebuilds when store.endpoints changes (pairing/removal),
#   * each row's state binds to store.devices, so a physical switch flip
#     (attribute_report -> gateway -> store.devices) flips the UI on its own,
#   * the add button reflects store.pairing.
#
# Toggles are optimistic: the store flips immediately for a responsive tap, and
# the 3s device poll (or the next report) confirms/corrects.

import lvgl as lv

import bridge
import shell
import store
import theme
from reactive import bind_text, effect
from widgets import w_card_button, w_group, w_label

_screen = None
_list = None
_row_effects = []


def _device_of(ieee):
    return store.devices.get().get(ieee) if ieee else None


def _state(ieee):
    device = _device_of(ieee)
    if device is None:
        return "—", theme.FAINT
    if device.get("unreachable"):
        return "לא זמין", theme.DANGER
    on = device.get("on_off")
    if on is None:
        return "—", theme.FAINT
    return ("דלוק", theme.SUCCESS) if on else ("כבוי", theme.MUTED)


def _toggle(ep_id, ieee):
    if not ieee:
        return                                    # not paired yet -> nothing to toggle
    device = _device_of(ieee)
    current = device.get("on_off") if device else None
    action = "off" if current else "on"          # unknown -> turn on
    # Optimistic flip so the tap feels instant; the poll/report confirms.
    devices = dict(store.devices.get())
    entry = dict(devices.get(ieee) or {})
    entry["on_off"] = (action == "on")
    devices[ieee] = entry
    store.devices.set(devices)
    bridge.dispatch(store.api, "control.send",
                    {"target_type": "endpoint", "target_id": ep_id,
                     "action_type": action})


def _rename(endpoint):
    import text_input
    text_input.open("שם המכשיר", endpoint.get("name") or "",
                    lambda name: _save_name(endpoint, name))


def _save_name(endpoint, name):
    if not name:
        return
    data = dict(endpoint)
    data["name"] = name
    bridge.dispatch(store.api, "endpoints.update",
                    {"id": endpoint["id"], "data": data})
    # Optimistic: reflect the new name now (the 3s poll would also catch it).
    updated = []
    for ep in store.endpoints.get():
        if ep["id"] == endpoint["id"]:
            ep = dict(ep)
            ep["name"] = name
        updated.append(ep)
    store.endpoints.set(updated)


def _device_row(parent, endpoint):
    ieee = endpoint.get("ieee_address")
    ep_id = endpoint["id"]
    row = w_group(parent, lv.FLEX_FLOW.ROW)
    row.set_width(lv.pct(100))
    row.set_style_pad_column(theme.GAP, lv.PART.MAIN)
    row.set_flex_align(lv.FLEX_ALIGN.START, lv.FLEX_ALIGN.CENTER,
                       lv.FLEX_ALIGN.CENTER)

    # name -> rename (Hebrew keyboard); grows to fill
    name = w_card_button(row)
    name.set_flex_grow(1)
    name.set_height(64)
    name.add_event_cb(lambda e: _rename(endpoint), lv.EVENT.CLICKED, None)
    w_label(name, theme.FONTS.title, theme.TEXT,
            endpoint.get("name") or "מכשיר").align(lv.ALIGN.RIGHT_MID, 0, 0)

    # state -> toggle (control); fixed width
    toggle = w_card_button(row)
    toggle.set_size(130, 64)
    toggle.add_event_cb(lambda e: _toggle(ep_id, ieee), lv.EVENT.CLICKED, None)
    state = w_label(toggle, theme.FONTS.body, theme.MUTED, "—")
    state.center()

    def _apply():
        text, color = _state(ieee)
        state.set_text(text)
        state.set_style_text_color(color, lv.PART.MAIN)

    _row_effects.append(effect(_apply))


def _rebuild():
    # Tracks store.endpoints: reruns when the device list changes. Must not read
    # store.devices here -- that stays inside each row's own effect.
    endpoints = store.endpoints.get()
    for eff in _row_effects:
        eff.dispose()
    del _row_effects[:]
    _list.clean()
    if not endpoints:
        w_label(_list, theme.FONTS.body, theme.MUTED,
                "אין מכשירים — הוסיפו מכשיר למטה").center()
        return
    for endpoint in endpoints:
        _device_row(_list, endpoint)


def _pairing_cb(e):
    starting = not store.pairing.get()
    store.pairing.set(starting)
    if starting:
        bridge.dispatch(store.api, "zigbee.permit_join", {"duration": 180})


def build():
    global _screen, _list
    scr, body = shell.page_create("הבית שלי")
    body.set_style_pad_all(16, lv.PART.MAIN)
    body.set_flex_flow(lv.FLEX_FLOW.COLUMN)
    body.set_style_pad_row(10, lv.PART.MAIN)

    _list = w_group(body, lv.FLEX_FLOW.COLUMN)
    _list.set_width(lv.pct(100))
    _list.set_flex_grow(1)
    _list.set_style_pad_row(8, lv.PART.MAIN)
    effect(_rebuild)

    add = w_card_button(body)
    add.set_width(lv.pct(100))
    add.set_height(52)
    add.set_style_bg_color(theme.PRIMARY, lv.PART.MAIN)
    add.add_event_cb(_pairing_cb, lv.EVENT.CLICKED, None)
    add_lbl = w_label(add, theme.FONTS.h1, theme.SURFACE, "")
    add_lbl.center()
    bind_text(add_lbl, lambda: "מחפש מכשיר… (ביטול)" if store.pairing.get()
              else "+ הוסף מכשיר")

    _screen = scr
    return scr
