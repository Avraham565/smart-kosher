# Clock-set screen -- the first real (non-placeholder) sub-page and the first
# UI->brain *write*. Tap a field to select it, type digits on the reusable
# numeric keyboard (keyboard.py), then confirm: the entered LOCAL time is
# converted to UTC and written to the RTC via the in-process brain (time.set).
#
# The city lives here too, because it is the other half of the same answer: a
# clock without a location cannot produce a zman. Tapping it opens city_picker
# (search + Hebrew keyboard) and the chosen id goes to settings.update, which
# applies that city's latitude, longitude AND elevation together -- the panel
# never sends coordinates of its own.
#
# Why local->UTC here: DeviceTimeService stores UTC (every displayed zman is
# derived from it through the settings offset), but a wall panel's user thinks in
# local Israel time. We fetch the DST-correct offset for the entered *date* from
# today.get (which already computes it), so summer/winter are both right, then
# subtract it.
#
# Render-safety: static page, instant load, a small key grid -- no scroll, no
# animation. Built once and cached; each open() resets the buffers.

import lvgl as lv

import bridge
import keyboard
import shell
import store
import theme
from widgets import w_card_button, w_group, w_label

# (key, label, width, min, max) -- entry order, shown as chips.
_FIELDS = (
    ("hour", "שעה", 2, 0, 23),
    ("minute", "דקה", 2, 0, 59),
    ("day", "יום", 2, 1, 31),
    ("month", "חודש", 2, 1, 12),
    ("year", "שנה", 4, 2013, 2099),
)
_DEFAULTS = {"hour": "12", "minute": "00", "day": "01",
             "month": "01", "year": "2026"}

_screen = None
_state = None


def _spec(key):
    for field in _FIELDS:
        if field[0] == key:
            return field
    return None


def _pad(buf, width):
    return ("0" * width + buf)[-width:]


# ── local -> UTC (offset is minutes; only ever shifts by <1 day) ────────────
def _days_in_month(year, month):
    if month == 2:
        leap = (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0)
        return 29 if leap else 28
    return 31 if month in (1, 3, 5, 7, 8, 10, 12) else 30


def _shift_day(year, month, day, delta):
    day += delta
    if day < 1:
        month -= 1
        if month < 1:
            month = 12
            year -= 1
        day = _days_in_month(year, month)
    elif day > _days_in_month(year, month):
        day = 1
        month += 1
        if month > 12:
            month = 1
            year += 1
    return year, month, day


def _local_to_utc(year, month, day, hour, minute, offset_min):
    total = hour * 60 + minute - offset_min
    if total < 0:
        year, month, day = _shift_day(year, month, day, -1)
        total += 1440
    elif total >= 1440:
        year, month, day = _shift_day(year, month, day, 1)
        total -= 1440
    return year, month, day, total // 60, total % 60


# ── view refresh ────────────────────────────────────────────────────────────
def _refresh():
    for key, label, width, lo, hi in _FIELDS:
        chip = _state["chips"][key]
        _state["vals"][key].set_text(_pad(_state["buf"][key], width))
        active = key == _state["active"]
        chip.set_style_bg_color(
            theme.PRIMARY_SOFT if active else theme.SURFACE, lv.PART.MAIN)
        chip.set_style_border_color(
            theme.PRIMARY if active else theme.LINE, lv.PART.MAIN)
        chip.set_style_border_width(2 if active else 1, lv.PART.MAIN)


def _set_msg(text, color):
    _state["msg"].set_text(text)
    _state["msg"].set_style_text_color(color, lv.PART.MAIN)


def _select(key):
    _state["active"] = key
    _refresh()


def _on_key(k):
    key = _state["active"]
    buf = _state["buf"][key]
    width = _spec(key)[2]
    if k == lv.SYMBOL.BACKSPACE:
        _state["buf"][key] = buf[:-1]
    else:
        # A digit on a full field starts the field over -- predictable retype.
        _state["buf"][key] = (k if len(buf) >= width else buf + k)
    _set_msg("", theme.FAINT)
    _refresh()


# ── confirm: validate -> local->UTC (DST-aware) -> time.set ────────────────
def _confirm(e):
    vals = {}
    for key, label, width, lo, hi in _FIELDS:
        value = int(_state["buf"][key] or "0")
        if not (lo <= value <= hi):
            _set_msg("ערך לא תקין: " + label, theme.DANGER)
            return
        vals[key] = value
    if vals["day"] > _days_in_month(vals["year"], vals["month"]):
        _set_msg("היום לא קיים בחודש הזה", theme.DANGER)
        return

    api = _state["api"]
    date = "%04d-%02d-%02d" % (vals["year"], vals["month"], vals["day"])
    _set_msg("שומר…", theme.MUTED)

    def _with_offset(today):
        offset = today.get("utc_offset_minutes", 120)
        y, mo, d, h, mi = _local_to_utc(
            vals["year"], vals["month"], vals["day"],
            vals["hour"], vals["minute"], offset)
        bridge.dispatch(
            api, "time.set",
            {"year": y, "month": mo, "day": d, "hour": h, "minute": mi,
             "second": 0},
            on_ok=lambda data: _saved(),
            on_err=lambda kind, msg: _set_msg("שגיאה: " + msg, theme.DANGER))

    bridge.dispatch(
        api, "today.get", {"date": date},
        on_ok=_with_offset,
        on_err=lambda kind, msg: _set_msg("שגיאה: " + msg, theme.DANGER))


def _saved():
    store.request_refresh()     # update the home clock now, don't wait for poll
    _done()


# ── city ────────────────────────────────────────────────────────────────────

def _show_city(name):
    _state["city"].set_text(name or "—")


def _load_city():
    """Fill the city chip from the brain. Failure leaves the dash: the chip is
    still tappable, so an unreadable setting cannot lock the user out of
    changing it."""
    bridge.dispatch(
        _state["api"], "settings.get", {},
        on_ok=lambda data: _show_city(data.get("city")),
        on_err=lambda kind, msg: _show_city(None))


def _pick_city(e):
    import city_picker

    def chosen(city_id):
        # Send the id alone -- the brain owns the geography behind the name.
        bridge.dispatch(
            _state["api"], "settings.update", {"data": {"city": city_id}},
            on_ok=lambda data: (_show_city(data.get("city")),
                                store.request_refresh()),
            on_err=lambda kind, msg: _set_msg("שגיאה: " + msg, theme.DANGER))

    city_picker.open(chosen)


def _done():
    import ui_home
    lv.screen_load(ui_home.screen())


# ── build (once) ────────────────────────────────────────────────────────────
def _build_chip(parent, key, label, width_px):
    chip = w_card_button(parent)
    chip.set_size(width_px, 64)
    chip.set_flex_flow(lv.FLEX_FLOW.COLUMN)
    chip.set_flex_align(lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER,
                        lv.FLEX_ALIGN.CENTER)
    chip.set_style_pad_row(2, lv.PART.MAIN)
    chip.add_event_cb(lambda e, k=key: _select(k), lv.EVENT.CLICKED, None)
    w_label(chip, theme.FONTS.small, theme.MUTED, label)
    value = w_label(chip, theme.FONTS.title, theme.TEXT, "")
    _state["chips"][key] = chip
    _state["vals"][key] = value


def _sep(parent, char):
    """A small ':' / '/' separator between chips (LTR, vertically centred)."""
    lbl = w_label(parent, theme.FONTS.title, theme.FAINT, char)
    lbl.set_style_base_dir(lv.BASE_DIR.LTR, lv.PART.MAIN)
    return lbl


def _field_row(body):
    """Time (שעה:דקה) and date (יום/חודש/שנה) as two grouped clusters, centred,
    LTR (numeric), with separators -- reads HH:MM   DD/MM/YYYY."""
    fields = w_group(body, lv.FLEX_FLOW.ROW)
    fields.set_width(lv.pct(100))
    fields.set_flex_align(lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER,
                          lv.FLEX_ALIGN.CENTER)
    fields.set_style_pad_column(36, lv.PART.MAIN)      # gap between time & date
    fields.set_style_base_dir(lv.BASE_DIR.LTR, lv.PART.MAIN)

    time_group = w_group(fields, lv.FLEX_FLOW.ROW)
    time_group.set_flex_align(lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER,
                              lv.FLEX_ALIGN.CENTER)
    time_group.set_style_pad_column(6, lv.PART.MAIN)
    _build_chip(time_group, "hour", "שעה", 92)
    _sep(time_group, ":")
    _build_chip(time_group, "minute", "דקה", 92)

    date_group = w_group(fields, lv.FLEX_FLOW.ROW)
    date_group.set_flex_align(lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER,
                              lv.FLEX_ALIGN.CENTER)
    date_group.set_style_pad_column(6, lv.PART.MAIN)
    _build_chip(date_group, "day", "יום", 82)
    _sep(date_group, "/")
    _build_chip(date_group, "month", "חודש", 82)
    _sep(date_group, "/")
    _build_chip(date_group, "year", "שנה", 116)


def _city_row(body):
    """One tappable line: the current city, and the way to change it.

    Height budget for this screen's 384px body, which has no scrollbar:
        fields 64 + city 38 + keypad 176 + actions 44 + msg 18 + gaps 32 = 372.
    Twelve pixels spare. Anything added here has to come out of something else.
    """
    row = w_card_button(body)
    row.set_width(lv.pct(100))
    row.set_height(38)
    row.add_event_cb(_pick_city, lv.EVENT.CLICKED, None)
    caption = w_label(row, theme.FONTS.small, theme.MUTED, "עיר")
    caption.align(lv.ALIGN.RIGHT_MID, 0, 0)
    name = w_label(row, theme.FONTS.body, theme.TEXT, "—")
    # Bounded so a long name cannot run into the caption on the right. The
    # caption is short and fixed; the name gets everything left of it.
    name.set_width(lv.pct(70))
    name.set_style_text_align(lv.TEXT_ALIGN.LEFT, lv.PART.MAIN)
    name.align(lv.ALIGN.LEFT_MID, 0, 0)
    _state["city"] = name


def _build(api):
    global _state
    scr, body = shell.page_create("כיוון שעה ותאריך")
    # Tighter padding than the shell default (24) -- the field row + keypad +
    # actions must all fit the 416px body without scrolling (no GRAM => scroll
    # is banned), so the אישור button stays on-screen and tappable.
    body.set_style_pad_all(16, lv.PART.MAIN)
    body.set_flex_flow(lv.FLEX_FLOW.COLUMN)
    body.set_flex_align(lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.START,
                        lv.FLEX_ALIGN.CENTER)
    # 8, not 10: five stacked rows now, and the body has no scrollbar to fall
    # back on. Measured budget is in the city-row comment below.
    body.set_style_pad_row(8, lv.PART.MAIN)

    _state = {"api": api, "buf": dict(_DEFAULTS), "active": "hour",
              "chips": {}, "vals": {}, "msg": None}

    _field_row(body)
    _city_row(body)

    # 38, not 40: the city row costs 42px and the body has no slack -- the
    # אישור button must stay on screen, because there is no scrolling to reach
    # it with.
    keyboard.build(body, keyboard.LAYOUT_NUMERIC, _on_key,
                   symbol_keys=(lv.SYMBOL.BACKSPACE,), key_height=38)

    actions = w_group(body, lv.FLEX_FLOW.ROW)
    actions.set_width(lv.pct(100))
    actions.set_style_pad_column(theme.GAP, lv.PART.MAIN)

    cancel = w_card_button(actions)
    cancel.set_flex_grow(1)
    cancel.set_height(44)
    cancel.add_event_cb(lambda e: _done(), lv.EVENT.CLICKED, None)
    w_label(cancel, theme.FONTS.body, theme.MUTED, "ביטול").center()

    ok = w_card_button(actions)
    ok.set_flex_grow(2)
    ok.set_height(44)
    ok.set_style_bg_color(theme.PRIMARY, lv.PART.MAIN)
    ok.add_event_cb(_confirm, lv.EVENT.CLICKED, None)
    w_label(ok, theme.FONTS.h1, theme.SURFACE, "אישור").center()

    _state["msg"] = w_label(body, theme.FONTS.small, theme.FAINT, "")

    return scr


def _initial_buffers():
    """Pre-fill with the current local time/date from the store, so the user only
    nudges values. Falls back to _DEFAULTS for anything unknown (clock never set)."""
    buf = dict(_DEFAULTS)
    now = store.now.get()
    if now is not None:
        buf["hour"] = "%02d" % now[0]
        buf["minute"] = "%02d" % now[1]
    today = store.today.get()
    date = today.get("date") if today else None
    if date:
        parts = date.split("-")            # YYYY-MM-DD
        if len(parts) == 3:
            buf["year"], buf["month"], buf["day"] = parts
    return buf


def open(api):
    """Build the clock-set screen on first use, pre-fill the current time, show it."""
    global _screen
    if _screen is None:
        _screen = _build(api)
    _state["api"] = api
    _state["buf"] = _initial_buffers()
    _state["active"] = "hour"
    _set_msg("", theme.FAINT)
    _refresh()
    # Re-read every open: the picker may have changed it since the last visit,
    # and returning from the picker lands back here.
    _load_city()
    lv.screen_load(_screen)
