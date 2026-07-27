#pragma once

#include "lvgl.h"

/* Reusable UI components — the small vocabulary every screen is built from,
 * so a working piece is written once and reused, not copy-pasted. theme.h
 * holds tokens + whole-object style helpers; this holds object factories.
 * All must be called with the lvgl_port lock held (like any LVGL call). */

/* A text label with font, colour and text set in one call. */
lv_obj_t *w_label(lv_obj_t *parent, const lv_font_t *font,
                  lv_color_t color, const char *text);

/* A transparent, border-less, non-scrolling flex container sized to its
 * content — the invisible box used purely to lay children out in a row/column
 * (LV_FLEX_FLOW_ROW / _COLUMN). */
lv_obj_t *w_group(lv_obj_t *parent, lv_flex_flow_t flow);

/* A small accent pill (rounded, 6px tall). */
lv_obj_t *w_stripe(lv_obj_t *parent, int width, lv_color_t color);

/* A top header band: full width × height, surface bg, 1px bottom line, no
 * scroll, given horizontal padding. Positioned at the top of its parent. */
lv_obj_t *w_header(lv_obj_t *parent, int height, int pad_hor);

/* A clickable card (th_card look + pressed feedback), ready for content and an
 * event callback. Size/flex are the caller's to set. */
lv_obj_t *w_card_button(lv_obj_t *parent);
