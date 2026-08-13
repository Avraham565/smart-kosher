# Reusable UI components — the small vocabulary every screen is built from, so a
# working piece is written once and reused, not copy-pasted. MicroPython twin of
# the C firmware's widgets.c (deleted 2026-08-05; see docs/display-lineage.md).
# theme.py holds tokens + whole-object style helpers; this holds object
# factories. All LVGL calls run from the asyncio pump (lvgl_loop.py).

import lvgl as lv

import theme


def w_label(parent, font, color, text):
    """A text label with font, colour and text set in one call."""
    lbl = lv.label(parent)
    lbl.set_style_text_font(font, lv.PART.MAIN)
    lbl.set_style_text_color(color, lv.PART.MAIN)
    lbl.set_text(text)
    return lbl


def w_group(parent, flow):
    """A transparent, border-less, non-scrolling flex container sized to its
    content — the invisible box used purely to lay children out in a row/column
    (lv.FLEX_FLOW.ROW / .COLUMN)."""
    g = lv.obj(parent)
    g.set_size(lv.SIZE_CONTENT, lv.SIZE_CONTENT)
    g.set_style_bg_opa(lv.OPA.TRANSP, lv.PART.MAIN)
    g.set_style_border_width(0, lv.PART.MAIN)
    g.set_style_pad_all(0, lv.PART.MAIN)
    g.remove_flag(lv.obj.FLAG.SCROLLABLE)
    g.set_flex_flow(flow)
    return g


def w_stripe(parent, width, color):
    """A small accent pill (rounded, 6px tall)."""
    s = lv.obj(parent)
    s.set_size(width, 6)
    s.set_style_bg_color(color, lv.PART.MAIN)
    s.set_style_radius(3, lv.PART.MAIN)
    s.set_style_border_width(0, lv.PART.MAIN)
    return s


def w_header(parent, height, pad_hor):
    """A top header band: full width x height, surface bg, 1px bottom line, no
    scroll, given horizontal padding. Positioned at the top of its parent."""
    h = lv.obj(parent)
    h.set_size(lv.pct(100), height)
    h.set_pos(0, 0)
    h.set_style_bg_color(theme.SURFACE, lv.PART.MAIN)
    h.set_style_radius(0, lv.PART.MAIN)
    h.set_style_border_width(1, lv.PART.MAIN)
    h.set_style_border_side(lv.BORDER_SIDE.BOTTOM, lv.PART.MAIN)
    h.set_style_border_color(theme.LINE, lv.PART.MAIN)
    h.set_style_pad_hor(pad_hor, lv.PART.MAIN)
    h.set_style_pad_ver(0, lv.PART.MAIN)
    h.remove_flag(lv.obj.FLAG.SCROLLABLE)
    return h


def w_card_button(parent):
    """A clickable card (theme.card look + pressed feedback), ready for content
    and an event callback. Size/flex are the caller's to set."""
    card = lv.obj(parent)
    theme.card(card)
    card.remove_flag(lv.obj.FLAG.SCROLLABLE)
    card.add_flag(lv.obj.FLAG.CLICKABLE)
    card.set_style_bg_color(theme.SURFACE_STRONG,
                            lv.PART.MAIN | lv.STATE.PRESSED)
    return card
