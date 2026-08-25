# Reusable text-entry screen (Hebrew keyboard). open(title, initial, on_ok)
# shows a field + the Hebrew letter keyboard + space / backspace / OK, and calls
# on_ok(text) with the trimmed result. Cancel (or the back arrow) returns without
# calling on_ok.
#
# Unlike the shell, "back" here returns to whatever screen invoked us (captured
# via lv.screen_active() at open), not home -- so renaming a device returns to
# the House page. Built once and cached; reconfigured per open.

import lvgl as lv

import keyboard
import theme
from widgets import w_card_button, w_group, w_header, w_label

_screen = None
_state = None
_title = None
_field = None


def _refresh():
    buf = _state["buf"]
    _field.set_text(buf if buf else _state["placeholder"])
    _field.set_style_text_color(theme.TEXT if buf else theme.FAINT, lv.PART.MAIN)


def _on_letter(ch):
    _state["buf"] += ch
    _refresh()


def _space(e):
    _state["buf"] += " "
    _refresh()


def _backspace(e):
    _state["buf"] = _state["buf"][:-1]
    _refresh()


def _leave():
    lv.screen_load(_state["return"])


def _cancel(e):
    _leave()


def _ok(e):
    text = _state["buf"].strip()
    on_ok = _state["on_ok"]
    _leave()
    if on_ok is not None:
        on_ok(text)


def _build():
    global _screen, _title, _field
    scr = lv.obj(None)
    theme.screen(scr)

    header = w_header(scr, 64, 18)
    _title = w_label(header, theme.FONTS.h1, theme.TEXT, "")
    _title.align(lv.ALIGN.RIGHT_MID, 0, 0)
    back = lv.button(header)
    back.set_size(100, theme.TAP_MIN)
    back.set_style_bg_color(theme.SURFACE_STRONG, lv.PART.MAIN)
    back.set_style_shadow_width(0, lv.PART.MAIN)
    back.align(lv.ALIGN.LEFT_MID, 0, 0)
    back.add_event_cb(_cancel, lv.EVENT.CLICKED, None)
    w_label(back, theme.FONTS.body, theme.TEXT, "ביטול").center()

    body = lv.obj(scr)
    body.set_size(lv.pct(100), 480 - 64)
    body.set_pos(0, 64)
    body.set_style_bg_opa(lv.OPA.TRANSP, lv.PART.MAIN)
    body.set_style_border_width(0, lv.PART.MAIN)
    body.set_style_pad_all(16, lv.PART.MAIN)
    body.remove_flag(lv.obj.FLAG.SCROLLABLE)
    body.set_flex_flow(lv.FLEX_FLOW.COLUMN)
    body.set_style_pad_row(10, lv.PART.MAIN)

    # text field
    field_box = w_card_button(body)
    field_box.set_width(lv.pct(100))
    field_box.set_height(56)
    field_box.remove_flag(lv.obj.FLAG.CLICKABLE)
    _field = w_label(field_box, theme.FONTS.title, theme.TEXT, "")
    _field.align(lv.ALIGN.RIGHT_MID, 0, 0)

    # spacer pushes the keyboard + actions to the bottom of the page
    spacer = lv.obj(body)
    spacer.set_width(lv.pct(100))
    spacer.set_flex_grow(1)
    spacer.set_style_bg_opa(lv.OPA.TRANSP, lv.PART.MAIN)
    spacer.set_style_border_width(0, lv.PART.MAIN)
    spacer.remove_flag(lv.obj.FLAG.SCROLLABLE)

    # letter keyboard
    keyboard.build(body, keyboard.LAYOUT_HEBREW, _on_letter, key_height=46)

    # action row (RTL): backspace on the right edge, a wide space bar in the
    # centre, OK on the left.
    actions = w_group(body, lv.FLEX_FLOW.ROW)
    actions.set_width(lv.pct(100))
    actions.set_style_pad_column(theme.GAP, lv.PART.MAIN)

    bksp = w_card_button(actions)
    bksp.set_flex_grow(1)
    bksp.set_height(50)
    bksp.add_event_cb(_backspace, lv.EVENT.CLICKED, None)
    w_label(bksp, theme.FONTS.symbol, theme.TEXT, lv.SYMBOL.BACKSPACE).center()

    space = w_card_button(actions)
    space.set_flex_grow(5)
    space.set_height(50)
    space.add_event_cb(_space, lv.EVENT.CLICKED, None)
    w_label(space, theme.FONTS.body, theme.MUTED, "רווח").center()

    ok = w_card_button(actions)
    ok.set_flex_grow(2)
    ok.set_height(50)
    ok.set_style_bg_color(theme.PRIMARY, lv.PART.MAIN)
    ok.add_event_cb(_ok, lv.EVENT.CLICKED, None)
    w_label(ok, theme.FONTS.h1, theme.SURFACE, "אישור").center()

    _screen = scr


def open(title, initial, on_ok, placeholder="הקלד שם"):
    """Show the text editor. Returns to the calling screen on OK/cancel; OK also
    calls on_ok(trimmed_text)."""
    global _state
    return_screen = lv.screen_active()
    if _screen is None:
        _build()
    _state = {"buf": initial or "", "on_ok": on_ok, "return": return_screen,
              "placeholder": placeholder}
    _title.set_text(title)
    _refresh()
    lv.screen_load(_screen)
