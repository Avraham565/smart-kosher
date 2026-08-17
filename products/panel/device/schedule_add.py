# Add-schedule wizard -- a step machine that assembles a schedule dict and
# creates it. One cached screen; the body re-renders per step; the header back
# steps one level (or exits at the first step). Steps:
#   target -> action -> trigger_type -> [fixed_time | zman (-> offset)] ->
#   recurrence -> [days] -> save
#
# Only the no-extra-date recurrences are offered for now (sched_labels
# .RECURRENCE_SIMPLE); the date-based ones come next. No Shabbat presets by
# request -- just the raw options.

import lvgl as lv

import bridge
import keyboard
import sched_labels
import shell
import store
import theme
import toast
from smart_kosher.domain.schedules import MAX_ZMAN_OFFSET_MINUTES
from widgets import w_card_button, w_group, w_label

_screen = None
_body = None
_title = None
_return = None
_draft = {}
_stack = []
_buf = ""
_offset_sign = -1
_target_zones = set()       # multi-select zone filter on the target step


# ── generic option grid ─────────────────────────────────────────────────────
def _grid(items, on_pick, cols=2, height=52, font=None):
    grid = w_group(_body, lv.FLEX_FLOW.ROW)
    grid.set_width(lv.pct(100))
    grid.set_flex_grow(1)
    grid.set_flex_flow(lv.FLEX_FLOW.ROW_WRAP)
    grid.set_style_pad_row(8, lv.PART.MAIN)
    grid.set_style_pad_column(8, lv.PART.MAIN)
    width = lv.pct(48) if cols == 2 else lv.pct(100 // cols - 2)
    for label, value in items:
        cell = w_card_button(grid)
        cell.set_width(width)
        cell.set_height(height)
        cell.add_event_cb(lambda e, v=value: on_pick(v), lv.EVENT.CLICKED, None)
        w_label(cell, font or theme.FONTS.body, theme.TEXT, label).center()


def _clear():
    _body.clean()


# ── steps ───────────────────────────────────────────────────────────────────
def _render():
    step = _stack[-1]
    _clear()
    _RENDERERS[step]()


def _goto(step):
    _stack.append(step)
    _render()


def _back():
    _stack.pop()
    if not _stack:
        lv.screen_load(_return)
    else:
        _render()


def _toggle_zone(zone_id):
    if zone_id in _target_zones:
        _target_zones.discard(zone_id)
    else:
        _target_zones.add(zone_id)
    _render()                                    # re-render the (filtered) step


def _pick_target(value):
    if value.startswith("g:"):
        _draft["target_type"] = "group"
        _draft["target_id"] = value[2:]
    else:
        _draft["target_type"] = "endpoint"
        _draft["target_id"] = value
    _goto("action")


def _zone_tags(tag_items):
    tags = w_group(_body, lv.FLEX_FLOW.ROW)
    tags.set_width(lv.pct(100))
    tags.set_flex_flow(lv.FLEX_FLOW.ROW_WRAP)
    tags.set_style_pad_row(6, lv.PART.MAIN)
    tags.set_style_pad_column(6, lv.PART.MAIN)
    for label, zone_id in tag_items:
        selected = zone_id in _target_zones
        chip = w_card_button(tags)
        chip.set_size(lv.SIZE_CONTENT, 38)
        chip.set_style_bg_color(
            theme.PRIMARY_SOFT if selected else theme.SURFACE, lv.PART.MAIN)
        chip.set_style_border_color(
            theme.PRIMARY if selected else theme.LINE, lv.PART.MAIN)
        chip.add_event_cb(lambda e, z=zone_id: _toggle_zone(z),
                          lv.EVENT.CLICKED, None)
        w_label(chip, theme.FONTS.small, theme.TEXT, label).center()


def _target():
    _title.set_text("מה לשלוט?")
    zones = store.zones.get()
    zone_ids = set(z["id"] for z in zones)
    # room tags + a "ללא חדר" tag for devices with no/unknown room (None marker)
    _zone_tags([(z["name"], z["id"]) for z in zones] + [("ללא חדר", None)])

    endpoints = store.endpoints.get()
    if _target_zones:
        def _match(ep):
            zid = ep.get("zone_id")
            return zid in _target_zones if zid in zone_ids else None in _target_zones
        endpoints = [ep for ep in endpoints if _match(ep)]
    items = [(ep.get("name") or "מכשיר", ep["id"]) for ep in endpoints]
    items += [("קבוצה: " + (g.get("name") or "קבוצה"), "g:" + g["id"])
              for g in store.groups.get()]
    if not items:
        w_label(_body, theme.FONTS.body, theme.MUTED,
                "אין מכשירים בבחירה").center()
        return
    _grid(items, _pick_target)


def _action():
    _title.set_text("פעולה")

    def pick(value):
        _draft["action_type"] = value
        _goto("trigger_type")
    _grid([("הדלק", "on"), ("כבה", "off")], pick, height=64,
          font=theme.FONTS.title)


def _trigger_type():
    _title.set_text("מתי?")

    def pick(value):
        _draft["trigger_type"] = value
        _goto("fixed_time" if value == "fixed_time" else "zman")
    _grid([("שעה קבועה", "fixed_time"), ("זמן הלכה", "zman"),
           ("זמן ± דקות", "zman_offset")], pick)


def _numeric(prompt, fmt, max_len, on_ok):
    global _buf
    _buf = ""
    _title.set_text(prompt)
    preview = w_label(_body, theme.FONTS.clock, theme.TEXT, fmt(""))
    preview.center()
    spacer = lv.obj(_body)
    spacer.set_width(lv.pct(100))
    spacer.set_flex_grow(1)
    spacer.set_style_bg_opa(lv.OPA.TRANSP, lv.PART.MAIN)
    spacer.set_style_border_width(0, lv.PART.MAIN)
    spacer.remove_flag(lv.obj.FLAG.SCROLLABLE)

    def on_key(k):
        global _buf
        if k == lv.SYMBOL.BACKSPACE:
            _buf = _buf[:-1]
        elif len(_buf) < max_len:
            _buf = _buf + k
        preview.set_text(fmt(_buf))
    keyboard.build(_body, keyboard.LAYOUT_NUMERIC, on_key,
                   symbol_keys=(lv.SYMBOL.BACKSPACE,), key_height=40)

    ok = w_card_button(_body)
    ok.set_width(lv.pct(100))
    ok.set_height(48)
    ok.set_style_bg_color(theme.PRIMARY, lv.PART.MAIN)
    ok.add_event_cb(lambda e: on_ok(_buf), lv.EVENT.CLICKED, None)
    w_label(ok, theme.FONTS.h1, theme.SURFACE, "אישור").center()


def _fmt_time(buf):
    padded = (buf + "____")[:4]
    return padded[:2] + ":" + padded[2:]


def _fixed_time():
    def on_ok(buf):
        b = (buf + "0000")[:4]
        hour, minute = int(b[:2]), int(b[2:])
        if hour > 23 or minute > 59:
            _title.set_text("שעה לא תקינה — HHMM")
            return
        _draft["trigger_type"] = "fixed_time"
        _draft["trigger_data"] = {"h": hour, "m": minute}
        _goto("recurrence")
    _numeric("שעה (HHMM)", _fmt_time, 4, on_ok)


def _zman():
    _title.set_text("זמן הלכה")
    items = [(sched_labels.ZMAN_NAMES[k], k) for k in sched_labels.ZMAN_ORDER]

    def pick(value):
        _draft["trigger_data"] = {"zman": value}
        _goto("offset" if _draft["trigger_type"] == "zman_offset"
              else "recurrence")
    _grid(items, pick, height=34, font=theme.FONTS.small)


def _offset():
    _title.set_text("היסט מהזמן")
    row = w_group(_body, lv.FLEX_FLOW.ROW)
    row.set_width(lv.pct(100))
    row.set_style_pad_column(8, lv.PART.MAIN)
    for label, sign in (("לפני", -1), ("אחרי", 1)):
        btn = w_card_button(row)
        btn.set_flex_grow(1)
        btn.set_height(48)
        if sign == _offset_sign:
            btn.set_style_bg_color(theme.PRIMARY_SOFT, lv.PART.MAIN)

        def choose(e, s=sign):
            global _offset_sign
            _offset_sign = s
            _render()
        btn.add_event_cb(choose, lv.EVENT.CLICKED, None)
        w_label(btn, theme.FONTS.body, theme.TEXT, label).center()

    def on_ok(buf):
        minutes = int(buf or "0")
        # Checked here for the same reason _fixed_time checks HH:MM: the keypad
        # takes four digits, the domain accepts -2880..2880 minutes
        # (domain/schedules.py), and the sign is chosen above -- so 0..2880 is
        # exactly the reachable range. Without this the wizard collected 9999,
        # the domain refused it, and the save vanished silently.
        if minutes > MAX_ZMAN_OFFSET_MINUTES:
            _title.set_text("היסט עד {} דק׳ (48 שעות)".format(
                MAX_ZMAN_OFFSET_MINUTES))
            return
        _draft.setdefault("trigger_data", {})["offset"] = _offset_sign * minutes
        _goto("recurrence")
    _numeric("דקות", lambda b: (b or "0") + " דק׳", 4, on_ok)


def _recurrence():
    _title.set_text("כל מתי?")
    items = [(sched_labels.RECURRENCE_NAMES[k], k)
             for k in sched_labels.RECURRENCE_SIMPLE]

    def pick(value):
        _draft["recurrence_type"] = value
        if value == "days_of_week":
            _goto("days")
        else:
            _draft["recurrence_data"] = {}
            _save()
    _grid(items, pick)


def _days():
    _title.set_text("ימים")
    chosen = set()
    grid = w_group(_body, lv.FLEX_FLOW.ROW)
    grid.set_width(lv.pct(100))
    grid.set_flex_flow(lv.FLEX_FLOW.ROW_WRAP)
    grid.set_style_pad_row(8, lv.PART.MAIN)
    grid.set_style_pad_column(8, lv.PART.MAIN)
    cells = {}

    def toggle(index):
        if index in chosen:
            chosen.discard(index)
        else:
            chosen.add(index)
        cell = cells[index]
        cell.set_style_bg_color(
            theme.PRIMARY_SOFT if index in chosen else theme.SURFACE,
            lv.PART.MAIN)

    for label, index in sched_labels.DAYS_OF_WEEK:
        cell = w_card_button(grid)
        cell.set_width(lv.pct(31))
        cell.set_height(48)
        cell.add_event_cb(lambda e, i=index: toggle(i), lv.EVENT.CLICKED, None)
        w_label(cell, theme.FONTS.body, theme.TEXT, label).center()
        cells[index] = cell

    ok = w_card_button(_body)
    ok.set_width(lv.pct(100))
    ok.set_height(48)
    ok.set_style_bg_color(theme.PRIMARY, lv.PART.MAIN)

    def done(e):
        if not chosen:
            return
        _draft["recurrence_data"] = {"days": sorted(chosen)}
        _save()
    ok.add_event_cb(done, lv.EVENT.CLICKED, None)
    w_label(ok, theme.FONTS.h1, theme.SURFACE, "אישור").center()


def _save():
    data = dict(_draft)
    data.setdefault("enabled", True)

    def ok(saved):
        _refresh()
        lv.screen_load(_return)

    def err(kind, message):
        # Stay on the wizard. Leaving unconditionally was how a schedule the
        # user had just finished building could simply never exist: the screen
        # closed exactly as it does on success, the list showed nothing new,
        # and the only clue was that the light never came on.
        toast.notify("התזמון לא נשמר — " + (message or "שגיאה"))

    if "id" in data:                             # editing an existing schedule
        bridge.dispatch(store.api, "schedules.update",
                        {"id": data["id"], "data": data},
                        on_ok=ok, on_err=err)
    else:
        bridge.dispatch(store.api, "schedules.create", {"data": data},
                        on_ok=ok, on_err=err)


def _refresh():
    bridge.dispatch(store.api, "schedules.list",
                    on_ok=lambda items: store.schedules.set(items))


_RENDERERS = {
    "target": _target, "action": _action, "trigger_type": _trigger_type,
    "fixed_time": _fixed_time, "zman": _zman, "offset": _offset,
    "recurrence": _recurrence, "days": _days,
}


def _build():
    global _screen, _body, _title
    scr, body, title = shell.sub_page("תזמון חדש", on_back=_back)
    body.set_style_pad_all(16, lv.PART.MAIN)
    body.set_flex_flow(lv.FLEX_FLOW.COLUMN)
    body.set_style_pad_row(10, lv.PART.MAIN)
    _screen, _body, _title = scr, body, title


def open(existing=None):
    """Open the wizard. With ``existing`` (a schedule dict) it edits it -- the
    draft keeps the id, so saving updates rather than creates."""
    global _return, _draft, _stack
    _return = lv.screen_active()
    if _screen is None:
        _build()
    _draft = dict(existing) if existing else {}
    _stack = []
    _target_zones.clear()
    _title.set_text("עריכת תזמון" if existing else "תזמון חדש")
    _goto("target")
    lv.screen_load(_screen)
