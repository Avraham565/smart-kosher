# HomeScreen — product A wall panel (the idle "wall clock" face). MicroPython
# twin of the C firmware's ui_home.c (deleted 2026-08-05; see
# docs/display-lineage.md).
#
# Layout (800x480, RTL), all static — no scroll, no animation:
#   header 110px: logo (right) . clock + Hebrew/Gregorian date (left)
#   body: hero button "הבית שלי" + a row of 4 (תזמונים / זמני הלכה /
#         לוח שנה / יציאה מהבית), all driven by the page registry
#   footer 34px: hub-link status line
#
# The arrangement (hero + 4) lives here and only here — pages.py stays neutral.
# Screens are built from the widgets vocabulary. Clock/date are mock scaffolding
# (see clock.py); tapping the clock opens a placeholder.

import lvgl as lv

import clock
import pages
import settime
import store
import theme
from reactive import effect
from widgets import w_card_button, w_group, w_header, w_label, w_stripe

_screen = None
_status = None
_footer_effect = None
_api = None           # the in-process brain Api, set by create()


def screen():
    """The home screen object, for detail screens that navigate back to it."""
    return _screen


# ------------------------------------------------------------------ #
# navigation                                                         #
# ------------------------------------------------------------------ #
def _settime_cb(e):
    settime.open(_api)


# ------------------------------------------------------------------ #
# header                                                             #
# ------------------------------------------------------------------ #
def _build_brand(header):
    cluster = w_group(header, lv.FLEX_FLOW.ROW)
    cluster.set_flex_align(lv.FLEX_ALIGN.START, lv.FLEX_ALIGN.CENTER,
                           lv.FLEX_ALIGN.CENTER)
    cluster.set_style_pad_column(12, lv.PART.MAIN)
    cluster.align(lv.ALIGN.RIGHT_MID, 0, 0)

    # logo mark — placeholder (solid primary + house glyph) until a real asset
    # is decided (image vs wordmark). RTL: sits at the right.
    mark = lv.obj(cluster)
    mark.set_size(52, 52)
    mark.set_style_bg_color(theme.PRIMARY, lv.PART.MAIN)
    mark.set_style_radius(12, lv.PART.MAIN)
    mark.set_style_border_width(0, lv.PART.MAIN)
    mark.set_style_pad_all(0, lv.PART.MAIN)
    mark.remove_flag(lv.obj.FLAG.SCROLLABLE)
    w_label(mark, theme.FONTS.symbol, theme.SURFACE, lv.SYMBOL.HOME).center()

    # wordmark
    words = w_group(cluster, lv.FLEX_FLOW.COLUMN)
    w_label(words, theme.FONTS.h1, theme.TEXT, "סמארט אנד כשר")
    en = w_label(words, theme.FONTS.small, theme.FAINT, "Smart & Kosher")
    en.set_style_base_dir(lv.BASE_DIR.LTR, lv.PART.MAIN)


def _build_timeblock(header):
    cluster = w_group(header, lv.FLEX_FLOW.ROW)
    cluster.set_style_pad_all(4, lv.PART.MAIN)          # tap target
    cluster.set_flex_align(lv.FLEX_ALIGN.START, lv.FLEX_ALIGN.CENTER,
                           lv.FLEX_ALIGN.CENTER)
    cluster.set_style_pad_column(16, lv.PART.MAIN)
    cluster.align(lv.ALIGN.LEFT_MID, 0, 0)
    cluster.add_flag(lv.obj.FLAG.CLICKABLE)
    cluster.add_event_cb(_settime_cb, lv.EVENT.CLICKED, None)

    # dates (right of the clock, toward centre)
    dates = w_group(cluster, lv.FLEX_FLOW.COLUMN)
    dates.set_style_pad_row(2, lv.PART.MAIN)

    # Hebrew line: day-of-week (primary) + rest (text). Bound to the clock, which
    # fills them from today.get on each refresh (empty until the first refresh).
    heb = w_group(dates, lv.FLEX_FLOW.ROW)
    heb.set_style_pad_column(6, lv.PART.MAIN)
    dow_lbl = w_label(heb, theme.FONTS.body, theme.PRIMARY, "")
    heb_lbl = w_label(heb, theme.FONTS.body, theme.TEXT, "")

    greg = w_label(dates, theme.FONTS.small, theme.MUTED, "")
    greg.set_style_base_dir(lv.BASE_DIR.LTR, lv.PART.MAIN)
    clock.bind_date(dow_lbl, heb_lbl, greg)

    # the clock itself — left edge
    clock.bind_time(w_label(cluster, theme.FONTS.clock, theme.TEXT, ""))


# ------------------------------------------------------------------ #
# nav cards                                                          #
# ------------------------------------------------------------------ #
def _build_hero(body):
    d = pages.page_def(pages.PAGE_HOUSE)
    card = w_card_button(body)
    card.set_width(lv.pct(100))
    card.set_flex_grow(3)
    card.add_event_cb(lambda e: pages.page_open(pages.PAGE_HOUSE),
                      lv.EVENT.CLICKED, None)

    w_stripe(card, 56, lv.color_hex(d[2])).align(lv.ALIGN.TOP_RIGHT, 0, 4)
    w_label(card, theme.FONTS.title, theme.TEXT, d[0]).align(
        lv.ALIGN.RIGHT_MID, 0, -6)
    w_label(card, theme.FONTS.body, theme.MUTED, d[1]).align(
        lv.ALIGN.RIGHT_MID, 0, 30)


def _build_navcard(row, page_id):
    d = pages.page_def(page_id)
    card = w_card_button(row)
    card.set_height(lv.pct(100))
    card.set_flex_grow(1)
    card.set_flex_flow(lv.FLEX_FLOW.COLUMN)
    card.set_flex_align(lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER,
                        lv.FLEX_ALIGN.CENTER)
    card.set_style_pad_row(10, lv.PART.MAIN)
    # default-arg pins page_id per iteration (no late-binding closure trap)
    card.add_event_cb(lambda e, pid=page_id: pages.page_open(pid),
                      lv.EVENT.CLICKED, None)

    w_stripe(card, 40, lv.color_hex(d[2]))
    w_label(card, theme.FONTS.h1, theme.TEXT, d[0])


# ------------------------------------------------------------------ #
# public                                                             #
# ------------------------------------------------------------------ #
def create(api):
    """Build the home UI on the active screen. Call after theme.load_fonts().
    ``api`` is the in-process brain, used by sub-screens (e.g. clock set)."""
    global _screen, _status, _api, _footer_effect
    _api = api
    scr = lv.screen_active()
    _screen = scr
    theme.screen(scr)

    # ---- header ----
    header = w_header(scr, 110, 26)
    _build_brand(header)
    _build_timeblock(header)

    # ---- body: hero + row of four ----
    body = lv.obj(scr)
    body.set_size(lv.pct(100), 336)
    body.set_pos(0, 110)
    body.set_style_bg_opa(lv.OPA.TRANSP, lv.PART.MAIN)
    body.set_style_border_width(0, lv.PART.MAIN)
    body.set_style_pad_all(18, lv.PART.MAIN)
    body.remove_flag(lv.obj.FLAG.SCROLLABLE)
    body.set_flex_flow(lv.FLEX_FLOW.COLUMN)
    body.set_style_pad_row(14, lv.PART.MAIN)

    _build_hero(body)

    row = w_group(body, lv.FLEX_FLOW.ROW)
    row.set_width(lv.pct(100))
    row.set_flex_grow(2)
    row.set_style_pad_column(14, lv.PART.MAIN)
    _build_navcard(row, pages.PAGE_SCHEDULES)
    _build_navcard(row, pages.PAGE_ZMANIM)
    _build_navcard(row, pages.PAGE_CALENDAR)
    _build_navcard(row, pages.PAGE_AWAY)

    # ---- footer status ----
    _status = w_label(scr, theme.FONTS.small, theme.FAINT, "")
    _status.align(lv.ALIGN.BOTTOM_MID, 0, -10)
    _footer_effect = effect(_apply_footer)   # re-renders on any store change


def _footer():
    """Footer (text, color) derived from the store -- reads the Signals so the
    effect that renders it re-runs whenever any of them change."""
    if not store.hub_online.get():
        return "המוח לא מגיב", theme.DANGER
    parts = ["מחובר למוח"]
    version = store.app_version.get()
    if version:
        parts.append("v" + version)
    link = store.h2_link.get()
    if link is True:
        parts.append("H2 מחובר")
    elif link is False:
        parts.append("H2 מנותק")
    if store.clock_unset.get():
        parts.append("השעון לא כוון")
    return " | ".join(parts), theme.SUCCESS


def _apply_footer():
    if _status is None:
        return
    text, color = _footer()
    _status.set_text(text)
    _status.set_style_text_color(color, lv.PART.MAIN)
    _status.align(lv.ALIGN.BOTTOM_MID, 0, -10)
