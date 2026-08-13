# Page registry — the neutral catalogue of destinations. MicroPython twin of
# the C firmware's page.{c,h} (deleted 2026-08-05; see experiments/_archive).
# It knows nothing about how the home screen arranges
# them (hero+4, a row, a grid); layout is purely a home-UI decision. Each page
# is a lazily-built placeholder for now: shell chrome (title + back) over an
# empty body. Real content fills the body per page later.

import lvgl as lv

import shell

# Page ids (index into _DEFS / _screens).
PAGE_HOUSE = 0        # הבית שלי
PAGE_SCHEDULES = 1    # תזמונים
PAGE_ZMANIM = 2       # זמני הלכה
PAGE_CALENDAR = 3     # לוח שנה
PAGE_AWAY = 4         # יציאה מהבית
PAGE_COUNT = 5

# One neutral row per destination: (title, subtitle, accent-hex). Accents mirror
# the home buttons.
_DEFS = (
    ("הבית שלי",   "אזורים ומכשירים",  0x0F766E),
    ("תזמונים",    "אוטומציות זמן",    0x2563EB),
    ("זמני הלכה",   "זריחה עד צאת",     0x15803D),
    ("לוח שנה",     "תאריך עברי ופרשה", 0xB45309),
    ("יציאה מהבית", "כיבוי מרוכז",      0xDC2626),
)

# Cached screens — each page built once, then reused (few pages, plenty of
# PSRAM; keeps navigation an instant swap).
_screens = [None] * PAGE_COUNT


def page_def(page_id):
    """(title, subtitle, accent_hex) for a page id, or None if out of range."""
    if page_id < 0 or page_id >= PAGE_COUNT:
        return None
    return _DEFS[page_id]


# Real builders per page id; ids not listed fall back to a placeholder.
def _builders():
    import rooms_page
    import schedules_page
    import zmanim_page
    return {PAGE_HOUSE: rooms_page.build, PAGE_SCHEDULES: schedules_page.build,
            PAGE_ZMANIM: zmanim_page.build}


def page_open(page_id):
    """Navigate to a page: build its screen on first open, then load it."""
    d = page_def(page_id)
    if d is None:
        return
    if _screens[page_id] is None:
        builder = _builders().get(page_id)
        if builder is not None:
            _screens[page_id] = builder()
        else:
            _screens[page_id] = shell.placeholder(d[0], d[1], lv.color_hex(d[2]))
    lv.screen_load(_screens[page_id])
