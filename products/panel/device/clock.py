# Clock/date bindings -- connects LVGL labels to the store's `now` / `today`
# Signals. No pushing, no timers here: bind a label once and it re-renders itself
# whenever the store changes (the ticker in main.py writes now/today). Works the
# same on the home header and on every sub-page corner clock.
#
# The RTC holds UTC; store.now already holds the local (UTC+offset) time.

import lvgl as lv

import hebdate
import store
from reactive import bind_text


def _time_text():
    value = store.now.get()
    return "--:--" if value is None else "%02d:%02d" % (value[0], value[1])


def _dow_text():
    today = store.today.get()
    return hebdate.day_of_week(today["day_of_week"]) if today else ""


def _hebrew_text():
    today = store.today.get()
    if not today:
        # Prompt only while the clock is unset; otherwise stay blank until data.
        return "· לחצו לכיוון השעה" if store.now.get() is None else ""
    heb = today.get("hebrew_date") or {}
    return "· " + hebdate.date_str(heb["year"], heb["month"], heb["day"])


def _gregorian_text():
    today = store.today.get()
    return _gregorian(today["date"]) if today else ""


def bind_time(label):
    """Bind a label to the live 'HH:MM'. LTR-forced so an RTL parent doesn't
    reorder the digits."""
    label.set_style_base_dir(lv.BASE_DIR.LTR, lv.PART.MAIN)
    return bind_text(label, _time_text)


def bind_date(dow_label, hebrew_label, gregorian_label):
    """Bind the three home-header date labels to the live Hebrew/Gregorian date."""
    bind_text(dow_label, _dow_text)
    bind_text(hebrew_label, _hebrew_text)
    bind_text(gregorian_label, _gregorian_text)


def _gregorian(iso):
    """'YYYY-MM-DD' -> 'DD/MM/YYYY'."""
    if not iso:
        return ""
    parts = iso.split("-")
    if len(parts) != 3:
        return iso
    return "{}/{}/{}".format(parts[2], parts[1], parts[0])
