# Reusable UI components — the small vocabulary every screen is built from, so a
# working piece is written once and reused, not copy-pasted. MicroPython twin of
# the C firmware's widgets.c (deleted 2026-08-05; see docs/display-lineage.md).
# theme.py holds tokens + whole-object style helpers; this holds object
# factories. All LVGL calls run from the asyncio pump (lvgl_loop.py).

import lvgl as lv

import theme

# The single place a dev_common STATE_* token becomes something visible. Both
# the room list and the device page render it, and a dict copied into each
# would be two vocabularies that agree until they do not -- the shape task 10
# went to some trouble to remove.
_STATE_LOOKS = {
    "on":          ("דלוק", "SUCCESS"),
    "off":         ("כבוי", "MUTED"),
    "unknown":     ("—", "FAINT"),
    "unreachable": ("לא זמין", "DANGER"),
}


def state_look(token):
    """(text, colour) for a dev_common state token."""
    text, colour = _STATE_LOOKS.get(token, _STATE_LOOKS["unknown"])
    return text, getattr(theme, colour)


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


def w_pager(parent, on_prev, on_next):
    """The pager controls — ``> prev | 2 / 3 | next <`` — as one compact group.

    Meant to sit in a page's bottom bar beside its add button, so paging costs
    no vertical budget of its own; on a 480px panel a dedicated row would have
    taken a whole card off every list. The arrows are TAP_MIN square, which is
    the same reason a shrinking card was rejected (see pager.py).

    RTL: the first child lands on the right, so "previous" is ``>``.
    ASCII rather than the typographic chevrons these used to be: the
    Assistant .bin fonts carry no U+203A/U+2039, so both rendered as
    boxes. Measured, not assumed -- see test_font_glyph_coverage.

    Returns (group, position_label, controls). Hide ``controls`` on a
    single-page list rather than removing them — the group keeps its size, so
    the capacity a page measured on the glass never changes underneath it.
    """
    size = theme.TAP_MIN + 8
    group = w_group(parent, lv.FLEX_FLOW.ROW)
    group.set_height(size)
    group.set_style_pad_column(6, lv.PART.MAIN)
    group.set_flex_align(lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER,
                         lv.FLEX_ALIGN.CENTER)

    prev = w_card_button(group)
    prev.set_size(size, size)
    prev.set_style_pad_all(0, lv.PART.MAIN)
    prev.add_event_cb(lambda e: on_prev(), lv.EVENT.CLICKED, None)
    w_label(prev, theme.FONTS.title, theme.TEXT, ">").center()

    # Fixed width: "1 / 1" and "10 / 12" must not resize the group and shove
    # the add button around on every page turn.
    position = w_label(group, theme.FONTS.body, theme.MUTED, "1 / 1")
    position.set_width(72)
    position.set_style_base_dir(lv.BASE_DIR.LTR, lv.PART.MAIN)
    position.set_style_text_align(lv.TEXT_ALIGN.CENTER, lv.PART.MAIN)

    nxt = w_card_button(group)
    nxt.set_size(size, size)
    nxt.set_style_pad_all(0, lv.PART.MAIN)
    nxt.add_event_cb(lambda e: on_next(), lv.EVENT.CLICKED, None)
    w_label(nxt, theme.FONTS.title, theme.TEXT, "<").center()

    return group, position, (prev, nxt)


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
