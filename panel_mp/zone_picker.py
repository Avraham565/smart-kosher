# Reusable room picker -- open(on_pick) shows the rooms (+ "ללא חדר"), and calls
# on_pick(zone_id) with the chosen zone id (None for no room). Fresh-built per
# open; returns to the caller on pick/back.

import lvgl as lv

import shell
import store
import theme
from widgets import w_card_button, w_group, w_label

_screen = None
_on_pick = None
_return = None


def _back():
    lv.screen_load(_return)


def _pick(zone_id):
    callback = _on_pick
    _back()
    if callback is not None:
        callback(zone_id)


def _build():
    scr, body = shell.page_create("בחר חדר", on_back=_back)
    body.set_style_pad_all(16, lv.PART.MAIN)
    grid = w_group(body, lv.FLEX_FLOW.ROW)
    grid.set_width(lv.pct(100))
    grid.set_flex_flow(lv.FLEX_FLOW.ROW_WRAP)
    grid.set_style_pad_row(8, lv.PART.MAIN)
    grid.set_style_pad_column(8, lv.PART.MAIN)
    options = [(z["name"], z["id"]) for z in store.zones.get()]
    options.append(("ללא חדר", None))
    for label, zone_id in options:
        cell = w_card_button(grid)
        cell.set_width(lv.pct(48))
        cell.set_height(56)
        cell.add_event_cb(lambda e, z=zone_id: _pick(z), lv.EVENT.CLICKED, None)
        w_label(cell, theme.FONTS.body, theme.TEXT, label).center()
    return scr


def open(on_pick):
    global _screen, _on_pick, _return
    _return = lv.screen_active()
    _on_pick = on_pick
    old = _screen
    _screen = _build()
    lv.screen_load(_screen)
    if old is not None:
        old.delete()
