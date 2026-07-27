#pragma once

#include "lvgl.h"

/* Mock wall clock. This is UI-only scaffolding: no RTC/SNTP yet, so the time
 * is a mock value that ticks one minute at a time. The point at this stage is
 * to exercise the real hardware path — a small, localized label repaint once a
 * minute is exactly the cheap update Track A handles well, so a ticking clock
 * is also a live stability probe. Real time replaces clock_tick() later.
 *
 * Call with the lvgl_port lock held (same as any LVGL call). */

/* Bind a label to receive the "HH:MM" string; updated now and on every tick.
 * A handful of labels can be bound (home header + shell corner). */
void clock_bind_time(lv_obj_t *label);

/* Start the once-a-minute mock tick. Call once, after the first bind. */
void clock_start(void);

/* Mock date strings (static for now). */
const char *clock_date_hebrew_dow(void);  /* "יום ה׳"            */
const char *clock_date_hebrew(void);      /* "ט׳ באב תשפ״ו"       */
const char *clock_date_gregorian(void);   /* "23/07/2026"         */
