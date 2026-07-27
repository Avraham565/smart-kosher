#pragma once

#include "lvgl.h"

/* App shell — the reusable frame every non-home page shares, so pages differ
 * only in their content, never in their chrome. Builds a fresh screen with a
 * thin 64px header (title on the right = RTL reading start, "חזרה" button on
 * the left, optional corner clock) over an empty body. Back always returns to
 * the home screen. Static page, instant swap — no scroll, no animation.
 *
 * Returns the screen object; *out_body receives the padded content container
 * to fill. Call with the lvgl_port lock held. */
lv_obj_t *shell_page_create(const char *title, lv_obj_t **out_body);

/* A ready-made "coming soon" page: shell chrome + a centred accent stripe,
 * subtitle and "בבנייה" note. The single placeholder mechanism shared by every
 * not-yet-built screen (registry pages and one-offs alike). Returns the screen
 * (load it with lv_screen_load). accent is an lv_color_hex-style value. */
lv_obj_t *shell_placeholder(const char *title, const char *subtitle,
                            lv_color_t accent);
