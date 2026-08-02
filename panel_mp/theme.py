# Design tokens mirroring product B's web UI (client/ui/style.css :root) and the
# C panel's theme.h 1:1, so both faces of the product match. This is the
# MicroPython twin of panel/main/ui/theme.h.
#
# Fonts load at runtime (lv.binfont_create) after the display is up, so unlike
# the C build they can't be compile-time constants. load_fonts() fills FONTS;
# call it once in main after _init_display(), before building any UI.

import lvgl as lv

# --- colors (css var -> hex) ------------------------------------------------
BG             = lv.color_hex(0xCDD6E0)   # --bg
SURFACE        = lv.color_hex(0xEEF3F7)   # --surface
SURFACE_SOFT   = lv.color_hex(0xE3EAF1)   # --surface-soft
SURFACE_STRONG = lv.color_hex(0xD3DDE7)   # --surface-strong
TEXT           = lv.color_hex(0x172033)   # --text
MUTED          = lv.color_hex(0x536171)   # --muted
FAINT          = lv.color_hex(0x8793A3)   # --faint
LINE           = lv.color_hex(0xB7C3D0)   # --line
PRIMARY        = lv.color_hex(0x0F766E)   # --primary
PRIMARY_STRONG = lv.color_hex(0x115E59)   # --primary-strong
PRIMARY_SOFT   = lv.color_hex(0xC9EAE4)   # --primary-soft
BLUE           = lv.color_hex(0x2563EB)   # --blue
AMBER          = lv.color_hex(0xB45309)   # --amber
AMBER_SOFT     = lv.color_hex(0xF3E3B8)   # --amber-soft
DANGER         = lv.color_hex(0xDC2626)   # --danger
SUCCESS        = lv.color_hex(0x15803D)   # --success
SUCCESS_SOFT   = lv.color_hex(0xCFEBDC)   # --success-soft

# --- shape / spacing --------------------------------------------------------
RADIUS  = 8      # --radius
PAD     = 14
GAP     = 10
TAP_MIN = 44     # --tap: minimum touch target


class _FontSet:
    # Assistant == open twin of product B's Segoe UI. Filled by load_fonts().
    # symbol is a Montserrat face (LV_SYMBOL_* glyphs live there, not in the
    # Hebrew-ranged Assistant .bin files).
    small = None
    body = None
    title = None
    h1 = None
    clock = None
    symbol = None


FONTS = _FontSet()

_font_refs = {}       # keep binfont refs alive — must not be GC'd while in use
_fs_registered = False


def _load_binfont(path):
    """Load an lv_font_conv .bin from the board VFS at runtime (S: driver)."""
    global _fs_registered
    if path in _font_refs:
        return _font_refs[path]
    try:
        import fs_driver
        if not _fs_registered:
            drv = lv.fs_drv_t()
            fs_driver.fs_register(drv, "S")
            _fs_registered = True
        font = lv.binfont_create("S:" + path)
        if font is None:
            raise ValueError("binfont_create returned None")
        _font_refs[path] = font
        return font
    except Exception as exc:
        print("font load failed (%s): %s" % (path, exc))
        return None


def load_fonts():
    """Populate FONTS. Assistant from VFS; a built-in fallback if any is
    missing so the UI still renders (tofu-free for Latin, DejaVu for Hebrew)."""
    heb_fallback = getattr(lv, "font_dejavu_16_persian_hebrew", None) \
        or lv.font_montserrat_16
    FONTS.small = _load_binfont("assistant_16.bin") or heb_fallback
    FONTS.body = _load_binfont("assistant_20.bin") or heb_fallback
    FONTS.title = _load_binfont("assistant_28.bin") or heb_fallback
    FONTS.h1 = _load_binfont("assistant_sb_28.bin") or heb_fallback
    FONTS.clock = _load_binfont("assistant_sb_48.bin") or heb_fallback
    # Montserrat for the logo glyph; 28 is rarely in the build, fall back to 16.
    FONTS.symbol = getattr(lv, "font_montserrat_28", None) \
        or lv.font_montserrat_16


# --- whole-object style helpers (twins of theme.h inline helpers) -----------
def card(obj):
    """Card base: surface bg, 1px line border, radius, pad. No shadow by design
    (a shadow is a per-rect software blur; a 1px border reads just as clean on
    this flat, light UI and costs no blur pass)."""
    obj.set_style_bg_color(SURFACE, lv.PART.MAIN)
    obj.set_style_radius(RADIUS, lv.PART.MAIN)
    obj.set_style_border_width(1, lv.PART.MAIN)
    obj.set_style_border_color(LINE, lv.PART.MAIN)
    obj.set_style_pad_all(PAD, lv.PART.MAIN)
    obj.set_style_shadow_width(0, lv.PART.MAIN)


def screen(scr):
    """Common screen base: bg, RTL, no free scrolling. The hardware wants static
    pages (RGB panel has no GRAM — see main.py); scrolling is what historically
    broke rendering, so every screen is non-scrollable by construction."""
    scr.set_style_bg_color(BG, lv.PART.MAIN)
    scr.set_style_base_dir(lv.BASE_DIR.RTL, lv.PART.MAIN)
    scr.remove_flag(lv.obj.FLAG.SCROLLABLE)
