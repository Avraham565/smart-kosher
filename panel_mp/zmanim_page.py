# Halachic times page -- the first read-only data screen and the acid test that
# the whole chain (RTC UTC + location + DST offset) is correct. Every time label
# binds to store.today (which the clock ticker already fills from today.get), so
# the page needs no dispatch of its own and refreshes itself at date rollover.
#
# 18 zmanim in two RTL columns (morning on the right), static -- no scroll (the
# RGB panel bans it). Times are already local "HH:MM" from the brain.
#
# "צאת הכוכבים" and "צאת שבת" show the same time on purpose: both are 8.5 below
# the horizon. They stay two rows because Shabbat exit is the concept schedules
# point at, so a stricter shiur later moves only that one.

import lvgl as lv

import hebdate
import shell
import store
import theme
from reactive import bind_text
from widgets import w_group, w_label

# (key, label) in chronological order. Right column = morning, left = evening.
_MORNING = (
    ("alot_hashachar", "עלות השחר"),
    ("talit_and_tefillin", "טלית ותפילין"),
    ("netz_hachama", "נץ החמה"),
    ("sof_zman_shema_mga", "סוף ק״ש מג״א"),
    ("sof_zman_shema_gra", "סוף ק״ש גר״א"),
    ("sof_zman_tfilla_mga", "סוף תפילה מג״א"),
    ("sof_zman_tfilla_gra", "סוף תפילה גר״א"),
    ("chatzot_hayom", "חצות היום"),
    ("mincha_gedola", "מנחה גדולה"),
    ("mincha_gedola_30min", "מנחה גדולה 30׳"),
)
_EVENING = (
    ("mincha_ketana", "מנחה קטנה"),
    ("plag_hamincha", "פלג המנחה"),
    ("candle_lighting", "הדלקת נרות"),
    ("shkia", "שקיעה"),
    ("tset_hakohavim", "צאת הכוכבים"),
    ("tset_hakohavim_shabbat", "צאת שבת"),
    ("tset_hakohavim_rabeinu_tam", "רבינו תם"),
    ("chatzot_halayla", "חצות הלילה"),
)

_screen = None


def _time_of(key):
    today = store.today.get()
    if not today:
        return "--:--"
    value = (today.get("zmanim") or {}).get(key)
    return value if value else "--:--"


def _date_text():
    today = store.today.get()
    if not today:
        return ""
    heb = today.get("hebrew_date") or {}
    parts = [hebdate.day_of_week(today.get("day_of_week")),
             hebdate.date_str(heb["year"], heb["month"], heb["day"])]
    parasha = hebdate.parasha_str(today.get("parasha"))
    if parasha:
        parts.append("פרשת " + parasha)
    return " · ".join(p for p in parts if p)


def _row(parent, key, label):
    row = w_group(parent, lv.FLEX_FLOW.ROW)
    row.set_width(lv.pct(100))
    row.set_flex_align(lv.FLEX_ALIGN.SPACE_BETWEEN, lv.FLEX_ALIGN.CENTER,
                       lv.FLEX_ALIGN.CENTER)
    w_label(row, theme.FONTS.small, theme.TEXT, label)
    time_lbl = w_label(row, theme.FONTS.body, theme.PRIMARY, "--:--")
    time_lbl.set_style_base_dir(lv.BASE_DIR.LTR, lv.PART.MAIN)   # tabular digits
    bind_text(time_lbl, lambda k=key: _time_of(k))


def _column(parent, rows):
    col = w_group(parent, lv.FLEX_FLOW.COLUMN)
    col.set_width(lv.pct(48))
    col.set_style_pad_row(6, lv.PART.MAIN)
    for key, label in rows:
        _row(col, key, label)
    return col


def build():
    global _screen
    scr, body = shell.page_create("זמני הלכה")
    body.set_style_pad_all(12, lv.PART.MAIN)
    body.set_flex_flow(lv.FLEX_FLOW.COLUMN)
    body.set_style_pad_row(8, lv.PART.MAIN)

    date = w_label(body, theme.FONTS.body, theme.MUTED, "")
    bind_text(date, _date_text)

    grid = w_group(body, lv.FLEX_FLOW.ROW)
    grid.set_width(lv.pct(100))
    grid.set_flex_grow(1)
    grid.set_flex_align(lv.FLEX_ALIGN.SPACE_BETWEEN, lv.FLEX_ALIGN.START,
                        lv.FLEX_ALIGN.START)
    _column(grid, _MORNING)     # RTL: first child = right column
    _column(grid, _EVENING)

    _screen = scr
    return scr
