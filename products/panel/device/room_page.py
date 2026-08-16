# Room screen -- the devices in one room. Rebuilt fresh for each room opened
# (parameterised by zone), and its previous instance is torn down (effects
# disposed, screen deleted) so nothing leaks. A device row: tap the name to open
# its detail page, tap the state to toggle (quick control). "+ הוסף מכשיר" pairs
# a new switch into THIS room.
#
# zone_id None is the "ללא חדר" bucket (devices with no/unknown room); it has no
# add button (you pair into a real room).

import lvgl as lv

import bridge
import dev_common
import shell
import store
import text_input
import theme
import toast
from reactive import bind_text, effect
from widgets import w_card_button, w_group, w_label

_screen = None
_list = None
_current = {}
_effects = []
_row_effects = []


def _endpoints_here():
    zone_id = _current["zone_id"]
    zone_ids = set(z["id"] for z in store.zones.get())
    result = []
    for endpoint in store.endpoints.get():
        ez = endpoint.get("zone_id")
        if zone_id is None:
            if ez not in zone_ids:
                result.append(endpoint)
        elif ez == zone_id:
            result.append(endpoint)
    return result


def _open_device(endpoint):
    import device_page
    device_page.open(endpoint)


def _add_device(e):
    zone_id = _current["zone_id"]
    if zone_id is None:
        return
    if store.pairing.get() == zone_id:
        store.pairing.set(None)                  # tap again -> cancel
    else:
        store.pairing.set(zone_id)
        bridge.dispatch(store.api, "zigbee.permit_join", {"duration": 180})


def _back():
    lv.screen_load(_current["return"])


def _rename_room(e):
    text_input.open("שם החדר", _current["name"] or "", _save_room_name)


def _save_room_name(name):
    if not name:
        return
    zone_id = _current["zone_id"]
    bridge.dispatch(store.api, "zones.update",
                    {"id": zone_id, "data": {"name": name}})
    updated = []
    for zone in store.zones.get():
        if zone["id"] == zone_id:
            zone = dict(zone)
            zone["name"] = name
        updated.append(zone)
    store.zones.set(updated)
    _current["name"] = name
    if _current.get("title") is not None:
        _current["title"].set_text(name)


def _delete_room(e):
    zone_id = _current["zone_id"]

    def ok(data):
        store.zones.set([z for z in store.zones.get() if z["id"] != zone_id])
        toast.notify("החדר נמחק")
        lv.screen_load(_current["return"])

    def err(kind, message):
        toast.notify("יש מכשירים בחדר — העבירו או הסירו אותם קודם"
                     if kind == "conflict" else "שגיאה במחיקת החדר")
    bridge.dispatch(store.api, "zones.delete", {"id": zone_id},
                    on_ok=ok, on_err=err)


def _device_row(parent, endpoint):
    ieee = endpoint.get("ieee_address")
    ep_id = endpoint["id"]
    row = w_group(parent, lv.FLEX_FLOW.ROW)
    row.set_width(lv.pct(100))
    row.set_style_pad_column(theme.GAP, lv.PART.MAIN)
    row.set_flex_align(lv.FLEX_ALIGN.START, lv.FLEX_ALIGN.CENTER,
                       lv.FLEX_ALIGN.CENTER)

    name = w_card_button(row)
    name.set_flex_grow(1)
    name.set_height(64)
    name.add_event_cb(lambda e: _open_device(endpoint), lv.EVENT.CLICKED, None)
    w_label(name, theme.FONTS.title, theme.TEXT,
            endpoint.get("name") or "מכשיר").align(lv.ALIGN.RIGHT_MID, 0, 0)

    toggle = w_card_button(row)
    toggle.set_size(120, 64)
    toggle.add_event_cb(lambda e: dev_common.device_toggle(ep_id, ieee),
                        lv.EVENT.CLICKED, None)
    state = w_label(toggle, theme.FONTS.body, theme.MUTED, "—")
    state.center()

    def _apply():
        text, color = dev_common.device_state(ieee)
        state.set_text(text)
        state.set_style_text_color(color, lv.PART.MAIN)

    _row_effects.append(effect(_apply))


def _rebuild():
    endpoints = _endpoints_here()          # tracks store.endpoints + store.zones
    for eff in _row_effects:
        eff.dispose()
    del _row_effects[:]
    _list.clean()
    if not endpoints:
        w_label(_list, theme.FONTS.body, theme.MUTED,
                "אין מכשירים בחדר").center()
        return
    for endpoint in endpoints:
        _device_row(_list, endpoint)


def _teardown():
    for eff in _effects:
        eff.dispose()
    del _effects[:]
    for eff in _row_effects:
        eff.dispose()
    del _row_effects[:]


def _build():
    global _list
    scr, body, title = shell.sub_page(_current["name"] or "חדר", on_back=_back,
                                      effects=_effects)
    _current["title"] = title
    body.set_style_pad_all(16, lv.PART.MAIN)
    body.set_flex_flow(lv.FLEX_FLOW.COLUMN)
    body.set_style_pad_row(10, lv.PART.MAIN)

    _list = w_group(body, lv.FLEX_FLOW.COLUMN)
    _list.set_width(lv.pct(100))
    _list.set_flex_grow(1)
    _list.set_style_pad_row(8, lv.PART.MAIN)
    _effects.append(effect(_rebuild))

    if _current["zone_id"] is not None:
        # room management: rename / delete
        manage = w_group(body, lv.FLEX_FLOW.ROW)
        manage.set_width(lv.pct(100))
        manage.set_style_pad_column(theme.GAP, lv.PART.MAIN)
        rename = w_card_button(manage)
        rename.set_flex_grow(1)
        rename.set_height(48)
        rename.add_event_cb(_rename_room, lv.EVENT.CLICKED, None)
        w_label(rename, theme.FONTS.body, theme.TEXT, "שנה שם חדר").center()
        delete = w_card_button(manage)
        delete.set_flex_grow(1)
        delete.set_height(48)
        delete.add_event_cb(_delete_room, lv.EVENT.CLICKED, None)
        w_label(delete, theme.FONTS.body, theme.DANGER, "מחק חדר").center()

        add = w_card_button(body)
        add.set_width(lv.pct(100))
        add.set_height(52)
        add.set_style_bg_color(theme.PRIMARY, lv.PART.MAIN)
        add.add_event_cb(_add_device, lv.EVENT.CLICKED, None)
        add_lbl = w_label(add, theme.FONTS.h1, theme.SURFACE, "")
        add_lbl.center()
        zone_id = _current["zone_id"]
        _effects.append(bind_text(
            add_lbl, lambda: "מחפש מכשיר… (ביטול)"
            if store.pairing.get() == zone_id else "+ הוסף מכשיר"))
    return scr


def open(zone_id, name):
    global _screen, _current
    return_screen = lv.screen_active()
    _teardown()
    old = _screen
    _current = {"zone_id": zone_id, "name": name, "return": return_screen}
    _screen = _build()
    lv.screen_load(_screen)
    if old is not None:
        old.delete()
