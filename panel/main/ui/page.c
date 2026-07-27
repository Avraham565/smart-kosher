#include "page.h"
#include "shell.h"

/* One neutral row per destination. Accents mirror the home buttons; they are
 * hex (not lv_color_hex()) because a static initializer can't call it. */
static const page_def_t s_pages[PAGE_COUNT] = {
    [PAGE_HOUSE]     = { "הבית שלי",    "אזורים ומכשירים",  0x0F766E },
    [PAGE_SCHEDULES] = { "תזמונים",     "אוטומציות זמן",    0x2563EB },
    [PAGE_ZMANIM]    = { "זמני הלכה",    "זריחה עד צאת",     0x15803D },
    [PAGE_CALENDAR]  = { "לוח שנה",      "תאריך עברי ופרשה", 0xB45309 },
    [PAGE_AWAY]      = { "יציאה מהבית",  "כיבוי מרוכז",      0xDC2626 },
};

/* Cached screens — each page built once, then reused (few pages, plenty of
 * PSRAM; keeps navigation an instant swap). */
static lv_obj_t *s_screens[PAGE_COUNT];

const page_def_t *page_def(page_id_t id)
{
    if (id < 0 || id >= PAGE_COUNT) {
        return NULL;
    }
    return &s_pages[id];
}

void page_open(page_id_t id)
{
    const page_def_t *def = page_def(id);
    if (!def) {
        return;
    }
    if (s_screens[id] == NULL) {
        s_screens[id] = shell_placeholder(def->title, def->subtitle,
                                          lv_color_hex(def->accent));
    }
    lv_screen_load(s_screens[id]);
}
