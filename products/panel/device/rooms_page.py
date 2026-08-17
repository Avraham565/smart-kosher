# Rooms screen -- what "הבית שלי" opens to. Lists the user's rooms (zones), each
# with a device count, plus "+ הוסף חדר" (Hebrew keyboard). Tap a room -> the
# room's devices. Devices with no room fall under a "ללא חדר" bucket.
#
# Reactive: the list rebuilds when store.zones or store.endpoints change. Built
# once and cached by pages.py.
#
# Pixel budget (800x480, and nothing here scrolls — see pager.py):
#     480 screen - 64 header                    = 416 body
#     416 - 2*16 body padding                   = 384
#     384 - 52 bottom bar - 10 pad_row          = 322 for the list
#     322 fits floor((322 + 8) / (72 + 8))      = 4 cards
# The pager shares the bottom bar with the add button precisely to keep that
# 322: a row of its own would have cost a card. The arithmetic above is the
# estimate — hwtest_ui.py measures the real capacity on the glass and pins
# ROOMS_PER_PAGE, and it is the measurement that wins.

import lvgl as lv

import bridge
import pager
import shell
import store
import text_input
import theme
from reactive import effect
from widgets import w_card_button, w_group, w_label, w_pager

# Pinned by hwtest_ui.test_lists_never_overflow_the_glass.
ROOMS_PER_PAGE = 4

_screen = None
_list = None
_effects = []
_page = 0
_pager_label = None
_pager_controls = ()


def _teardown():
    """Release this page's bindings before its screen is deleted.

    pages.py builds this screen once and keeps it, so in the product nothing
    ever deletes it. hwtest_ui does, to measure how many cards fit, and an
    effect is owned by the Signal it read rather than by the widget -- without
    this, each rebuilt screen would leave the last one's bindings writing
    set_text into freed memory.
    """
    for eff in _effects:
        eff.dispose()
    del _effects[:]


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


def _turn(delta):
    global _page
    _page += delta
    _rebuild()          # clamped there; nothing else may assume _page is valid


def _sync_pager(total):
    _pager_label.set_text(pager.label(_page, total, ROOMS_PER_PAGE))
    many = pager.page_count(total, ROOMS_PER_PAGE) > 1
    for control in _pager_controls:
        if many:
            control.remove_flag(lv.obj.FLAG.HIDDEN)
        else:
            control.add_flag(lv.obj.FLAG.HIDDEN)


def _rebuild():
    global _page
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

    # Explicit order, not the repository's. Two rebuilds of the same data must
    # put every room on the same page, or the 3-second poll would shuffle rooms
    # between pages under the user's finger. Name first because that is what
    # they see; id breaks ties so two rooms named alike cannot swap.
    rows = [(zone["id"], zone["name"]) for zone in zones]
    rows.sort(key=lambda row: (row[1], row[0]))
    if unassigned:
        rows.append((None, "ללא חדר"))     # the bucket stays last, unsorted

    _page = pager.clamp_page(_page, len(rows), ROOMS_PER_PAGE)
    if not rows:
        w_label(_list, theme.FONTS.body, theme.MUTED,
                "אין חדרים — הוסיפו חדר למטה").center()
    for zone_id, name in pager.page_items(rows, _page, ROOMS_PER_PAGE):
        _room_card(_list, zone_id, name, counts.get(zone_id, 0))
    _sync_pager(len(rows))


def build():
    global _screen, _list, _pager_label, _pager_controls
    _teardown()          # a rebuild must not leave the last build's effects live
    scr, body = shell.page_create("הבית שלי", effects=_effects)
    body.set_style_pad_all(16, lv.PART.MAIN)
    body.set_flex_flow(lv.FLEX_FLOW.COLUMN)
    body.set_style_pad_row(10, lv.PART.MAIN)

    _list = w_group(body, lv.FLEX_FLOW.COLUMN)
    _list.set_width(lv.pct(100))
    _list.set_flex_grow(1)
    _list.set_style_pad_row(8, lv.PART.MAIN)

    # The bottom bar is built before the effect runs: _rebuild writes the pager
    # label on its very first pass, so the widgets have to exist by then.
    bar = w_group(body, lv.FLEX_FLOW.ROW)
    bar.set_width(lv.pct(100))
    bar.set_height(theme.TAP_MIN + 8)
    bar.set_style_pad_column(theme.GAP, lv.PART.MAIN)
    _, _pager_label, _pager_controls = w_pager(
        bar, lambda: _turn(-1), lambda: _turn(1))

    add = w_card_button(bar)
    add.set_flex_grow(1)
    add.set_height(theme.TAP_MIN + 8)
    add.set_style_bg_color(theme.PRIMARY, lv.PART.MAIN)
    add.add_event_cb(_add_room, lv.EVENT.CLICKED, None)
    w_label(add, theme.FONTS.h1, theme.SURFACE, "+ הוסף חדר").center()

    _effects.append(effect(_rebuild))

    _screen = scr
    return scr
