# Global transient notification -- one label on the top layer (above every
# screen), bound to store.toast, auto-cleared a few seconds after notify().
# Used to surface errors that used to fail silently (e.g. a delete rejected by
# referential integrity) and brief confirmations.

import time

import lvgl as lv

import store
import theme
from reactive import effect

_DURATION_MS = 3500
_label = None
_shown_at = 0


def _apply():
    message = store.toast.get()
    if not message:
        _label.add_flag(lv.obj.FLAG.HIDDEN)
        return
    _label.set_text(message)
    _label.remove_flag(lv.obj.FLAG.HIDDEN)
    _label.align(lv.ALIGN.BOTTOM_MID, 0, -24)


def _clear_tick(timer):
    if store.toast.get() and time.ticks_diff(time.ticks_ms(), _shown_at) > _DURATION_MS:
        store.toast.set("")


def install():
    """Create the toast label on the top layer and start the auto-clear tick.
    Call once after fonts are loaded."""
    global _label
    _label = lv.label(lv.layer_top())
    _label.set_style_bg_color(theme.TEXT, lv.PART.MAIN)
    _label.set_style_bg_opa(235, lv.PART.MAIN)
    _label.set_style_text_color(theme.SURFACE, lv.PART.MAIN)
    _label.set_style_text_font(theme.FONTS.body, lv.PART.MAIN)
    _label.set_style_pad_all(14, lv.PART.MAIN)
    _label.set_style_radius(10, lv.PART.MAIN)
    _label.set_width(lv.pct(88))                 # default long mode wraps
    _label.set_style_base_dir(lv.BASE_DIR.RTL, lv.PART.MAIN)
    _label.align(lv.ALIGN.BOTTOM_MID, 0, -24)
    _label.add_flag(lv.obj.FLAG.HIDDEN)
    effect(_apply)
    lv.timer_create(_clear_tick, 500, None)


def notify(message):
    global _shown_at
    _shown_at = time.ticks_ms()
    store.toast.set(message)
