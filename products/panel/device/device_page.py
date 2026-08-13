# Device page -- one device's detail: a big state/toggle, rename (Hebrew
# keyboard, the ONLY place a device is renamed), and remove. Rebuilt fresh per
# device; the previous instance is torn down. Back returns to the room.

import lvgl as lv

import bridge
import dev_common
import shell
import store
import text_input
import theme
import toast
import zone_picker
from reactive import effect
from widgets import w_card_button, w_group, w_label

_screen = None
_current = {}
_effects = []


def _endpoint():
    return _current["endpoint"]


def _back():
    lv.screen_load(_current["return"])


def _toggle(e):
    ep = _endpoint()
    dev_common.device_toggle(ep["id"], ep.get("ieee_address"))


def _rename(e):
    text_input.open("שם המכשיר", _endpoint().get("name") or "", _save_name)


def _save_name(name):
    if not name:
        return
    ep = _endpoint()
    data = dict(ep)
    data["name"] = name
    bridge.dispatch(store.api, "endpoints.update",
                    {"id": ep["id"], "data": data})
    updated = []
    for item in store.endpoints.get():
        if item["id"] == ep["id"]:
            item = dict(item)
            item["name"] = name
        updated.append(item)
    store.endpoints.set(updated)
    ep = dict(ep)
    ep["name"] = name
    _current["endpoint"] = ep
    _current["title"].set_text(name)


def _remove(e):
    # No optimistic delete: it can be rejected (device used by a schedule/group).
    # Wait for the result and only then remove + leave, or show why it failed.
    ep = _endpoint()

    def ok(data):
        store.endpoints.set(
            [x for x in store.endpoints.get() if x["id"] != ep["id"]])
        toast.notify("המכשיר הוסר")
        _back()

    def err(kind, message):
        toast.notify("לא ניתן להסיר — המכשיר בשימוש בתזמון או בקבוצה"
                     if kind == "conflict" else "שגיאה במחיקת המכשיר")
    bridge.dispatch(store.api, "endpoints.delete", {"id": ep["id"]},
                    on_ok=ok, on_err=err)


def _move(e):
    zone_picker.open(_apply_move)


def _apply_move(zone_id):
    ep = _endpoint()
    data = dict(ep)
    if zone_id:
        data["zone_id"] = zone_id
    else:
        data.pop("zone_id", None)          # unassign = omit the key (not None)

    def ok(result):
        updated = []
        moved = None
        for item in store.endpoints.get():
            if item["id"] == ep["id"]:
                item = dict(item)
                if zone_id:
                    item["zone_id"] = zone_id
                else:
                    item.pop("zone_id", None)
                moved = item
            updated.append(item)
        store.endpoints.set(updated)
        if moved is not None:
            _current["endpoint"] = moved
        toast.notify("המכשיר הועבר")
    bridge.dispatch(store.api, "endpoints.update", {"id": ep["id"], "data": data},
                    on_ok=ok, on_err=lambda k, m: toast.notify("שגיאה בהעברה"))


def _teardown():
    for eff in _effects:
        eff.dispose()
    del _effects[:]


def _build():
    ep = _endpoint()
    scr, body, title = shell.sub_page(ep.get("name") or "מכשיר", on_back=_back)
    _current["title"] = title
    body.set_flex_flow(lv.FLEX_FLOW.COLUMN)
    body.set_style_pad_row(14, lv.PART.MAIN)
    body.set_flex_align(lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.START,
                        lv.FLEX_ALIGN.CENTER)

    ieee = ep.get("ieee_address")
    toggle = w_card_button(body)
    toggle.set_width(lv.pct(100))
    toggle.set_flex_grow(1)
    toggle.add_event_cb(_toggle, lv.EVENT.CLICKED, None)
    state = w_label(toggle, theme.FONTS.clock, theme.MUTED, "—")
    state.center()

    def _apply():
        text, color = dev_common.device_state(ieee)
        state.set_text(text)
        state.set_style_text_color(color, lv.PART.MAIN)

    _effects.append(effect(_apply))

    actions = w_group(body, lv.FLEX_FLOW.ROW)
    actions.set_width(lv.pct(100))
    actions.set_style_pad_column(theme.GAP, lv.PART.MAIN)

    rename = w_card_button(actions)
    rename.set_flex_grow(1)
    rename.set_height(56)
    rename.add_event_cb(_rename, lv.EVENT.CLICKED, None)
    w_label(rename, theme.FONTS.body, theme.TEXT, "שנה שם").center()

    move = w_card_button(actions)
    move.set_flex_grow(1)
    move.set_height(56)
    move.add_event_cb(_move, lv.EVENT.CLICKED, None)
    w_label(move, theme.FONTS.body, theme.TEXT, "העבר").center()

    remove = w_card_button(actions)
    remove.set_flex_grow(1)
    remove.set_height(56)
    remove.add_event_cb(_remove, lv.EVENT.CLICKED, None)
    w_label(remove, theme.FONTS.body, theme.DANGER, "הסר מכשיר").center()

    return scr


def open(endpoint):
    global _screen, _current
    return_screen = lv.screen_active()
    _teardown()
    old = _screen
    _current = {"endpoint": endpoint, "return": return_screen, "title": None}
    _screen = _build()
    lv.screen_load(_screen)
    if old is not None:
        old.delete()
