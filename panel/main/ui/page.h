#pragma once

#include "lvgl.h"

/* Page registry — the neutral catalogue of destinations. It knows nothing
 * about how the home screen arranges them (hero+4, a row, a grid); layout is
 * purely a home-UI decision. Each page is a lazily-built placeholder for now:
 * shell chrome (title + back) over an empty body. Real content fills the body
 * per page later. */
typedef enum {
    PAGE_HOUSE = 0,   /* הבית שלי      */
    PAGE_SCHEDULES,   /* תזמונים       */
    PAGE_ZMANIM,      /* זמני הלכה      */
    PAGE_CALENDAR,    /* לוח שנה        */
    PAGE_AWAY,        /* יציאה מהבית    */
    PAGE_COUNT,
} page_id_t;

typedef struct {
    const char *title;
    const char *subtitle;
    uint32_t    accent;   /* hex; lv_color_hex() at build time (not const-safe) */
} page_def_t;

/* Registry lookup. NULL if id is out of range. */
const page_def_t *page_def(page_id_t id);

/* Navigate to a page: build its screen on first open, then load it (instant
 * swap). Call with the lvgl_port lock held. */
void page_open(page_id_t id);
