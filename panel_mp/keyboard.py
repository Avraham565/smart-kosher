# Reusable on-screen keyboard -- a static grid of keys built from the widgets
# vocabulary (w_card_button), so it is render-safe on the RGB panel (no scroll,
# no animation, no full-screen churn) and matches the rest of the UI.
#
# Generic by design: `build` renders any `layout` (rows of key strings) and calls
# `on_key(key)` on each press. The caller owns the text/field buffer and decides
# what each key means -- so the SAME component serves the numeric clock now and a
# Hebrew name keyboard later (just a different layout + on_key).
#
# Special/glyph keys (e.g. lv.SYMBOL.BACKSPACE) are drawn with the symbol font;
# pass them in `symbol_keys`. An empty-string key renders as an invisible spacer
# to keep a ragged row aligned to the grid.

import lvgl as lv

import theme
from widgets import w_card_button, w_group, w_label

_KEY_HEIGHT = 48

# 3-column numeric pad: 1-9, then backspace / 0 / spacer.
LAYOUT_NUMERIC = (
    ("1", "2", "3"),
    ("4", "5", "6"),
    ("7", "8", "9"),
    (lv.SYMBOL.BACKSPACE, "0", ""),
)

# Standard Israeli letter layout (matches phone keyboards), incl. final letters.
# Rendered left-to-right (ltr=True) like a physical keyboard; single Hebrew
# glyphs have no direction of their own.
LAYOUT_HEBREW = (
    ("ק", "ר", "א", "ט", "ו", "ן", "ם", "פ"),
    ("ש", "ד", "ג", "כ", "ע", "י", "ח", "ל", "ך", "ף"),
    ("ז", "ס", "ב", "ה", "נ", "מ", "צ", "ת", "ץ"),
)


def _spacer(parent):
    s = lv.obj(parent)
    s.set_style_bg_opa(lv.OPA.TRANSP, lv.PART.MAIN)
    s.set_style_border_width(0, lv.PART.MAIN)
    s.remove_flag(lv.obj.FLAG.SCROLLABLE)
    s.set_flex_grow(1)
    s.set_height(_KEY_HEIGHT)
    return s


def build(parent, layout, on_key, key_font=None, symbol_keys=(),
          key_height=_KEY_HEIGHT, ltr=True):
    """Render `layout` (rows of key strings) as a full-width key grid and wire
    every key to ``on_key(key)``. ``symbol_keys`` are drawn with the symbol font;
    ``""`` is an invisible spacer. ``ltr`` forces left-to-right key order (the
    numeric pad reads 1-2-3 left to right even under an RTL screen); a Hebrew
    layout would pass ltr=False. Returns the grid container."""
    key_font = key_font or theme.FONTS.title
    symbol_keys = set(symbol_keys)

    grid = w_group(parent, lv.FLEX_FLOW.COLUMN)
    grid.set_width(lv.pct(100))
    grid.set_style_pad_row(theme.GAP, lv.PART.MAIN)
    if ltr:
        # Base direction drives flex-row order and is inherited by the rows;
        # LTR keeps digits in reading order on the RTL screen.
        grid.set_style_base_dir(lv.BASE_DIR.LTR, lv.PART.MAIN)

    for row in layout:
        r = w_group(grid, lv.FLEX_FLOW.ROW)
        r.set_width(lv.pct(100))
        r.set_style_pad_column(theme.GAP, lv.PART.MAIN)
        for key in row:
            if key == "":
                _spacer(r)
                continue
            btn = w_card_button(r)
            btn.set_flex_grow(1)
            btn.set_height(key_height)
            font = theme.FONTS.symbol if key in symbol_keys else key_font
            w_label(btn, font, theme.TEXT, key).center()
            btn.add_event_cb(lambda e, k=key: on_key(k), lv.EVENT.CLICKED, None)

    return grid
