# Room screen -- the devices in one room. Rebuilt fresh for each room opened
# (parameterised by zone), and its previous instance is torn down (effects
# disposed, screen deleted) so nothing leaks. A device row: tap the name to open
# its detail page, tap the state to toggle (quick control). "+ הוסף מכשיר" pairs
# a new switch into THIS room.
#
# zone_id None is the "ללא חדר" bucket (devices with no/unknown room); it has no
# add button (you pair into a real room).
#
# Pixel budget (800x480, and nothing here scrolls — see pager.py). This is the
# tightest of the three list pages, because it is the only one carrying a
# manage row as well:
#     480 screen - 64 header                          = 416 body
#     416 - 2*16 body padding                         = 384
#     384 - 48 manage - 52 bottom bar - 2*10 pad_row  = 264 for the list
#     264 fits floor((264 + 8) / (64 + 8))            = 3 rows
# The "ללא חדר" bucket has no manage row and fits four, but one page cannot
# have two capacities, so the worst case governs both. The arithmetic is the
# estimate — hwtest_ui.py measures the real capacity and pins DEVICES_PER_PAGE.

import lvgl as lv

import bridge
import dev_common
import pager
import shell
import store
import text_input
import theme
import toast
from reactive import bind_text, effect
from widgets import w_card_button, w_group, w_label, w_pager

# Pinned by hwtest_ui.test_lists_never_overflow_the_glass.
DEVICES_PER_PAGE = 3

_screen = None
_list = None
_current = {}
_effects = []
_row_effects = []
_page = 0
_pager_label = None
_pager_controls = ()


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
        # The window is open; the screen shows what walks in. Nothing is
        # adopted until the user picks a row -- main._try_autopair used to do
        # it for them, one entity per device, before they had chosen anything.
        import add_device_page
        add_device_page.open(zone_id)


def _back():
    lv.screen_load(_current["return"])


def _rename_room(e):
    text_input.open("שם החדר", _current["name"] or "", _save_room_name)


def _save_room_name(name):
    if not name:
        return
    zone_id = _current["zone_id"]

    def ok(saved):
        # Applied here rather than straight after dispatch. A rename is rare
        # and deliberate, so there is nothing to buy by showing it before it
        # is saved -- and a title that changed on a write the repository
        # refused is a lie the 3-second poll would quietly take back.
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

    bridge.dispatch(store.api, "zones.update",
                    {"id": zone_id, "data": {"name": name}},
                    on_ok=ok,
                    on_err=lambda kind, message: toast.notify(
                        "שם החדר לא נשמר"))


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


def _turn(delta):
    global _page
    _page += delta
    _rebuild()          # clamped there; nothing else may assume _page is valid


def _sync_pager(total):
    _pager_label.set_text(pager.label(_page, total, DEVICES_PER_PAGE))
    many = pager.page_count(total, DEVICES_PER_PAGE) > 1
    for control in _pager_controls:
        if many:
            control.remove_flag(lv.obj.FLAG.HIDDEN)
        else:
            control.add_flag(lv.obj.FLAG.HIDDEN)


def _rebuild():
    global _page
    endpoints = _endpoints_here()          # tracks store.endpoints + store.zones
    for eff in _row_effects:
        eff.dispose()
    del _row_effects[:]
    _list.clean()
    # Explicit order, not the repository's: the 3-second poll rebuilds this
    # list constantly, and a device that hops pages between rebuilds is a
    # device the user's finger misses. Name first, id to break ties.
    endpoints = sorted(endpoints,
                       key=lambda ep: (ep.get("name") or "", ep["id"]))
    _page = pager.clamp_page(_page, len(endpoints), DEVICES_PER_PAGE)
    if not endpoints:
        w_label(_list, theme.FONTS.body, theme.MUTED,
                "אין מכשירים בחדר").center()
        _sync_pager(0)
        return
    for endpoint in pager.page_items(endpoints, _page, DEVICES_PER_PAGE):
        _device_row(_list, endpoint)
    _sync_pager(len(endpoints))


def _teardown():
    for eff in _effects:
        eff.dispose()
    del _effects[:]
    for eff in _row_effects:
        eff.dispose()
    del _row_effects[:]


def _build():
    global _list, _pager_label, _pager_controls
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

    # The bottom bar exists in both cases, so the "ללא חדר" bucket keeps the
    # same list geometry as a real room. Built before the effect: _rebuild
    # writes the pager label on its first pass.
    bar = w_group(body, lv.FLEX_FLOW.ROW)
    bar.set_width(lv.pct(100))
    bar.set_height(theme.TAP_MIN + 8)
    bar.set_style_pad_column(theme.GAP, lv.PART.MAIN)
    _, _pager_label, _pager_controls = w_pager(
        bar, lambda: _turn(-1), lambda: _turn(1))

    if _current["zone_id"] is not None:
        add = w_card_button(bar)
        add.set_flex_grow(1)
        add.set_height(theme.TAP_MIN + 8)
        add.set_style_bg_color(theme.PRIMARY, lv.PART.MAIN)
        add.add_event_cb(_add_device, lv.EVENT.CLICKED, None)
        add_lbl = w_label(add, theme.FONTS.h1, theme.SURFACE, "")
        add_lbl.center()
        zone_id = _current["zone_id"]
        _effects.append(bind_text(
            add_lbl, lambda: "מחפש מכשיר… (ביטול)"
            if store.pairing.get() == zone_id else "+ הוסף מכשיר"))

    _effects.append(effect(_rebuild))
    return scr


def open(zone_id, name):
    global _screen, _current, _page
    return_screen = lv.screen_active()
    _teardown()
    # A different room is a different list, so paging starts over. This is the
    # one reset that is right: clamp_page holds the index across rebuilds of
    # the *same* list, which is a separate question from opening another one.
    _page = 0
    old = _screen
    _current = {"zone_id": zone_id, "name": name, "return": return_screen}
    _screen = _build()
    lv.screen_load(_screen)
    if old is not None:
        old.delete()
