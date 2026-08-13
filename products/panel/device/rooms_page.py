# Rooms screen -- what "הבית שלי" opens to. Lists the user's rooms (zones), each
# with a device count, plus "+ הוסף חדר" (Hebrew keyboard). Tap a room -> the
# room's devices. Devices with no room fall under a "ללא חדר" bucket.
#
# Reactive: the list rebuilds when store.zones or store.endpoints change. Built
# once and cached by pages.py.

import lvgl as lv

import bridge
import shell
import store
import text_input
import theme
from reactive import effect
from widgets import w_card_button, w_group, w_label

_screen = None
_list = None
_list_effect = None


def _refresh_zones():
    bridge.dispatch(store.api, "zones.list",
                    on_ok=lambda zones: store.zones.set(zones))


def _create_room(name):
    if not name:
        return
    bridge.dispatch(store.api, "zones.create", {"data": {"name": name}},
                    on_ok=lambda z: _refresh_zones())


def _add_room(e):
    text_input.open("שם החדר", "", _create_room)


def _open_room(zone_id, name):
    import room_page
    room_page.open(zone_id, name)


def _room_card(parent, zone_id, name, count):
    card = w_card_button(parent)
    card.set_width(lv.pct(100))
    card.set_height(72)
    card.set_flex_flow(lv.FLEX_FLOW.ROW)
    card.set_flex_align(lv.FLEX_ALIGN.SPACE_BETWEEN, lv.FLEX_ALIGN.CENTER,
                        lv.FLEX_ALIGN.CENTER)
    card.add_event_cb(lambda e: _open_room(zone_id, name), lv.EVENT.CLICKED, None)
    w_label(card, theme.FONTS.title, theme.TEXT, name)
    w_label(card, theme.FONTS.body, theme.MUTED, "{} מכשירים".format(count))


def _rebuild():
    zones = store.zones.get()
    endpoints = store.endpoints.get()
    _list.clean()
    zone_ids = set(z["id"] for z in zones)
    counts = {}
    unassigned = 0
    for ep in endpoints:
        zid = ep.get("zone_id")
        if zid in zone_ids:
            counts[zid] = counts.get(zid, 0) + 1
        else:
            unassigned += 1
    if not zones and not unassigned:
        w_label(_list, theme.FONTS.body, theme.MUTED,
                "אין חדרים — הוסיפו חדר למטה").center()
    for zone in zones:
        _room_card(_list, zone["id"], zone["name"], counts.get(zone["id"], 0))
    if unassigned:
        _room_card(_list, None, "ללא חדר", unassigned)


def build():
    global _screen, _list, _list_effect
    scr, body = shell.page_create("הבית שלי")
    body.set_style_pad_all(16, lv.PART.MAIN)
    body.set_flex_flow(lv.FLEX_FLOW.COLUMN)
    body.set_style_pad_row(10, lv.PART.MAIN)

    _list = w_group(body, lv.FLEX_FLOW.COLUMN)
    _list.set_width(lv.pct(100))
    _list.set_flex_grow(1)
    _list.set_style_pad_row(8, lv.PART.MAIN)
    _list_effect = effect(_rebuild)

    add = w_card_button(body)
    add.set_width(lv.pct(100))
    add.set_height(52)
    add.set_style_bg_color(theme.PRIMARY, lv.PART.MAIN)
    add.add_event_cb(_add_room, lv.EVENT.CLICKED, None)
    w_label(add, theme.FONTS.h1, theme.SURFACE, "+ הוסף חדר").center()

    _screen = scr
    return scr
