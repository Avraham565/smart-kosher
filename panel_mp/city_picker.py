# Reusable city picker -- open(on_pick) shows a Hebrew search field, the letter
# keyboard, and the matches for what has been typed so far. Calls
# on_pick(city_id) with the chosen city; back/cancel returns without calling it.
#
# Search rather than a list because the RGB panel bans scrolling and forty
# cities do not fit on one 800x480 screen at a legible size. Two letters cut the
# list to a handful, so every match is a large, static button -- no scroll, no
# paging, no animation.
#
# The matching itself is NOT here: it lives in smart_kosher.data.search_cities,
# so it is one implementation shared with the rest of the product and is tested
# on its own, without a display. This module owns only the screen.
#
# Built once and cached, reconfigured per open -- same contract as text_input.

import lvgl as lv

import keyboard
import theme
from smart_kosher.data import search_cities
from widgets import w_card_button, w_group, w_header, w_label

# Four is what fits between the field and the keyboard at a tappable height.
# Anything more and the user should type another letter instead.
MAX_RESULTS = 4

_screen = None
_state = None
_title = None
_field = None
_hint = None
_result_slots = ()


def matches(query):
    """The cities offered for `query`, and how many were left out."""
    found = search_cities(query)
    return found[:MAX_RESULTS], max(0, len(found) - MAX_RESULTS)


def _refresh():
    query = _state["buf"]
    _field.set_text(query if query else "הקלד את שם העיר")
    _field.set_style_text_color(theme.TEXT if query else theme.FAINT,
                                lv.PART.MAIN)

    shown, hidden = matches(query)
    _state["shown"] = shown

    for index, (button, label) in enumerate(_result_slots):
        if index < len(shown):
            label.set_text(shown[index]["name_he"])
            button.remove_flag(lv.obj.FLAG.HIDDEN)
        else:
            button.add_flag(lv.obj.FLAG.HIDDEN)

    if not shown:
        _hint.set_text("אין עיר בשם הזה")
    elif hidden:
        _hint.set_text("ועוד {} — המשך להקליד".format(hidden))
    else:
        _hint.set_text("")


def _on_letter(ch):
    _state["buf"] += ch
    _refresh()


def _backspace(e):
    _state["buf"] = _state["buf"][:-1]
    _refresh()


def _clear(e):
    _state["buf"] = ""
    _refresh()


def _leave():
    lv.screen_load(_state["return"])


def _cancel(e):
    _leave()


def _choose(index):
    shown = _state["shown"]
    if index >= len(shown):
        return
    city_id = shown[index]["id"]
    on_pick = _state["on_pick"]
    _leave()
    if on_pick is not None:
        on_pick(city_id)


def _build():
    """Height budget for the 392px body (416 minus 12 padding each side).

        field 48 + results 112 + keyboard 128 + actions 46 + gaps 32 = 366

    Twenty-six spare, taken up by the spacer that pins the keyboard to the
    bottom. There is no scrollbar on this panel: whatever does not fit is drawn
    off the page and lost. hwtest_ui measures the built tree in absolute screen
    coordinates, so a row that stops fitting fails the suite rather than
    quietly disappearing.
    """
    global _screen, _title, _field, _hint, _result_slots
    scr = lv.obj(None)
    theme.screen(scr)

    header = w_header(scr, 64, 18)
    _title = w_label(header, theme.FONTS.h1, theme.TEXT, "בחר עיר")
    _title.align(lv.ALIGN.RIGHT_MID, 0, 0)
    back = lv.button(header)
    back.set_size(100, theme.TAP_MIN)
    back.set_style_bg_color(theme.SURFACE_STRONG, lv.PART.MAIN)
    back.set_style_shadow_width(0, lv.PART.MAIN)
    back.align(lv.ALIGN.LEFT_MID, 0, 0)
    back.add_event_cb(_cancel, lv.EVENT.CLICKED, None)
    w_label(back, theme.FONTS.body, theme.TEXT, "› ביטול").center()

    body = lv.obj(scr)
    body.set_size(lv.pct(100), 480 - 64)
    body.set_pos(0, 64)
    body.set_style_bg_opa(lv.OPA.TRANSP, lv.PART.MAIN)
    body.set_style_border_width(0, lv.PART.MAIN)
    body.set_style_pad_all(12, lv.PART.MAIN)
    body.remove_flag(lv.obj.FLAG.SCROLLABLE)
    body.set_flex_flow(lv.FLEX_FLOW.COLUMN)
    body.set_style_pad_row(8, lv.PART.MAIN)

    # what has been typed
    field_box = w_card_button(body)
    field_box.set_width(lv.pct(100))
    field_box.set_height(48)
    field_box.remove_flag(lv.obj.FLAG.CLICKABLE)
    _field = w_label(field_box, theme.FONTS.title, theme.TEXT, "")
    _field.set_width(lv.pct(65))
    _field.align(lv.ALIGN.RIGHT_MID, 0, 0)

    # The hint shares the field's line rather than owning a row. As its own row
    # it cost 29px plus a gap, and the body does not have them: the action row
    # ended 8px below the bottom edge of the screen, where there is no scrollbar
    # to reach it. Measured budget is in the layout note above _build.
    _hint = w_label(field_box, theme.FONTS.small, theme.MUTED, "")
    _hint.set_width(lv.pct(33))
    _hint.align(lv.ALIGN.LEFT_MID, 0, 0)

    # matches: two columns, two rows, each slot pre-built and shown/hidden.
    # Rebuilding these per keystroke would churn the display list on every tap,
    # which is exactly what this panel punishes.
    grid = w_group(body, lv.FLEX_FLOW.ROW)
    grid.set_width(lv.pct(100))
    grid.set_flex_flow(lv.FLEX_FLOW.ROW_WRAP)
    grid.set_style_pad_row(8, lv.PART.MAIN)
    grid.set_style_pad_column(8, lv.PART.MAIN)
    slots = []
    for index in range(MAX_RESULTS):
        cell = w_card_button(grid)
        cell.set_width(lv.pct(48))
        cell.set_height(52)
        cell.add_event_cb(lambda e, i=index: _choose(i), lv.EVENT.CLICKED, None)
        # center() returns None in the LVGL bindings, so the label has to be
        # bound before it is positioned -- chaining stores a null and the first
        # refresh dies on set_text.
        label = w_label(cell, theme.FONTS.body, theme.TEXT, "")
        # Bounded, not content-sized. w_label leaves a label to size itself to
        # its text, which on a fixed-width button means a long name spills out
        # of the card and over its neighbour. Given a width it wraps instead,
        # and the cell is tall enough for the second line. hwtest_ui measures
        # every city against this width so the wrap is a backstop, not the
        # normal case.
        label.set_width(lv.pct(100))
        label.set_style_text_align(lv.TEXT_ALIGN.CENTER, lv.PART.MAIN)
        label.center()
        slots.append((cell, label))
    _result_slots = tuple(slots)

    # push the keyboard to the bottom edge
    spacer = lv.obj(body)
    spacer.set_width(lv.pct(100))
    spacer.set_flex_grow(1)
    spacer.set_style_bg_opa(lv.OPA.TRANSP, lv.PART.MAIN)
    spacer.set_style_border_width(0, lv.PART.MAIN)
    spacer.remove_flag(lv.obj.FLAG.SCROLLABLE)

    keyboard.build(body, keyboard.LAYOUT_HEBREW, _on_letter, key_height=40)

    # No OK button: choosing a match IS the confirmation. Space is not here
    # either -- a word prefix already finds "בני ברק" from either word.
    actions = w_group(body, lv.FLEX_FLOW.ROW)
    actions.set_width(lv.pct(100))
    actions.set_style_pad_column(theme.GAP, lv.PART.MAIN)

    bksp = w_card_button(actions)
    bksp.set_flex_grow(1)
    bksp.set_height(46)
    bksp.add_event_cb(_backspace, lv.EVENT.CLICKED, None)
    w_label(bksp, theme.FONTS.symbol, theme.TEXT, lv.SYMBOL.BACKSPACE).center()

    clear = w_card_button(actions)
    clear.set_flex_grow(2)
    clear.set_height(46)
    clear.add_event_cb(_clear, lv.EVENT.CLICKED, None)
    w_label(clear, theme.FONTS.body, theme.MUTED, "נקה").center()

    _screen = scr


def open(on_pick, title="בחר עיר"):
    """Show the picker. Returns to the calling screen on pick or cancel; a pick
    also calls on_pick(city_id)."""
    global _state
    return_screen = lv.screen_active()
    if _screen is None:
        _build()
    _state = {"buf": "", "on_pick": on_pick, "return": return_screen, "shown": []}
    _title.set_text(title)
    _refresh()
    lv.screen_load(_screen)
