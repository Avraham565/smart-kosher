# App shell — the reusable frame every non-home page shares, so pages differ
# only in their content, never in their chrome. MicroPython twin of
# the C firmware's shell.c (deleted 2026-08-05; see docs/display-lineage.md).
# A fresh screen with a thin 64px header (title on the
# right = RTL reading start, "חזרה" on the left, optional corner clock) over an
# empty body. Back always returns home. Static page, instant swap.

import lvgl as lv

import clock
import theme
from widgets import w_header, w_label, w_stripe

# Corner clock on sub-pages: product decision still open. True = always-visible
# time in the sub-page header (the mockup showed it); False = title + back only.
SHELL_CORNER_CLOCK = True


def _back_cb(e):
    # Deferred import breaks the shell<->ui_home cycle (ui_home builds pages that
    # build shells). Instant swap, no animation — full-screen animation is the
    # exact churn the RGB panel can't feed.
    import ui_home
    lv.screen_load(ui_home.screen())


def sub_page(title, on_back=None, effects=None):
    """Like page_create, but also returns the title label so a page can update
    it live (e.g. after a rename). Returns (screen, body, title_label).

    ``effects`` is a list the shell appends its own bindings to (today: the
    corner clock). **A page that deletes its screen must pass one and dispose
    everything in it before delete().** A bound effect is owned by the Signal it
    read (reactive.Signal._observers holds it strongly), not by the widget, so an
    effect nobody kept a handle to can never be unsubscribed -- it outlives the
    screen and writes set_text into freed memory on the next tick. Accumulating
    into the caller's list instead of returning a fourth tuple element keeps
    every existing caller unpacking the same way.
    """
    scr = lv.obj(None)          # parentless obj == a screen (lv_obj_create(NULL))
    theme.screen(scr)

    # ---- thin header (64px) ----
    header = w_header(scr, 64, 18)

    # title — right edge (RTL reading start)
    title_lbl = w_label(header, theme.FONTS.h1, theme.TEXT, title)
    title_lbl.align(lv.ALIGN.RIGHT_MID, 0, 0)

    # back button — left edge
    back = lv.button(header)
    back.set_size(100, theme.TAP_MIN)
    back.set_style_bg_color(theme.SURFACE_STRONG, lv.PART.MAIN)
    back.set_style_bg_color(theme.LINE, lv.PART.MAIN | lv.STATE.PRESSED)
    back.set_style_shadow_width(0, lv.PART.MAIN)
    back.align(lv.ALIGN.LEFT_MID, 0, 0)
    handler = _back_cb if on_back is None else (lambda e: on_back())
    back.add_event_cb(handler, lv.EVENT.CLICKED, None)
    w_label(back, theme.FONTS.body, theme.TEXT, "חזרה").center()

    if SHELL_CORNER_CLOCK:
        mini = w_label(header, theme.FONTS.body, theme.MUTED, "")
        mini.align(lv.ALIGN.LEFT_MID, 116, 0)   # just right of back
        eff = clock.bind_time(mini)
        if effects is not None:
            effects.append(eff)

    # ---- body ----
    body = lv.obj(scr)
    body.set_size(lv.pct(100), 480 - 64)
    body.set_pos(0, 64)
    body.set_style_bg_opa(lv.OPA.TRANSP, lv.PART.MAIN)
    body.set_style_border_width(0, lv.PART.MAIN)
    body.set_style_pad_all(24, lv.PART.MAIN)
    body.remove_flag(lv.obj.FLAG.SCROLLABLE)
    return scr, body, title_lbl


def page_create(title, on_back=None, effects=None):
    """Build a sub-page screen. Returns (screen, body) — body is the padded
    content container to fill. Load the screen with lv.screen_load(). ``on_back``
    overrides where the back button goes (default: home); pass a 0-arg callable
    so nested screens (room -> device) can step back one level. ``effects`` is
    passed through to sub_page — see there; a page that deletes its screen must
    pass one."""
    scr, body, _ = sub_page(title, on_back, effects)
    return scr, body


def placeholder(title, subtitle, accent):
    """A ready-made "coming soon" page: shell chrome + a centred accent stripe,
    subtitle and "בבנייה" note. The single placeholder mechanism shared by every
    not-yet-built screen. Returns the screen (load it with lv.screen_load).
    accent is an lv.color_hex value."""
    scr, body = page_create(title)
    w_stripe(body, 56, accent).align(lv.ALIGN.CENTER, 0, -44)
    w_label(body, theme.FONTS.title, theme.TEXT, subtitle).align(
        lv.ALIGN.CENTER, 0, 0)
    w_label(body, theme.FONTS.body, theme.FAINT, "המסך בבנייה").align(
        lv.ALIGN.CENTER, 0, 44)
    return scr
