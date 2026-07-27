/* Design tokens mirroring product B's web UI (client/ui/style.css :root).
 * Keep 1:1 with the CSS variables so both faces of the product match. */
#pragma once

#include "lvgl.h"
#include "fonts/fonts.h"

/* --- colors (css var -> hex) --- */
#define TH_BG             lv_color_hex(0xF6F7FB)   /* --bg */
#define TH_SURFACE        lv_color_hex(0xFFFFFF)   /* --surface */
#define TH_SURFACE_SOFT   lv_color_hex(0xF9FAFB)   /* --surface-soft */
#define TH_SURFACE_STRONG lv_color_hex(0xEDF2F7)   /* --surface-strong */
#define TH_TEXT           lv_color_hex(0x172033)   /* --text */
#define TH_MUTED          lv_color_hex(0x667085)   /* --muted */
#define TH_FAINT          lv_color_hex(0x98A2B3)   /* --faint */
#define TH_LINE           lv_color_hex(0xE4E7EC)   /* --line */
#define TH_PRIMARY        lv_color_hex(0x0F766E)   /* --primary */
#define TH_PRIMARY_STRONG lv_color_hex(0x115E59)   /* --primary-strong */
#define TH_PRIMARY_SOFT   lv_color_hex(0xD9F4EF)   /* --primary-soft */
#define TH_BLUE           lv_color_hex(0x2563EB)   /* --blue */
#define TH_AMBER          lv_color_hex(0xB45309)   /* --amber */
#define TH_AMBER_SOFT     lv_color_hex(0xFFF4D6)   /* --amber-soft */
#define TH_DANGER         lv_color_hex(0xDC2626)   /* --danger */
#define TH_SUCCESS        lv_color_hex(0x15803D)   /* --success */
#define TH_SUCCESS_SOFT   lv_color_hex(0xDCFCE7)   /* --success-soft */

/* --- shape / spacing --- */
#define TH_RADIUS   8      /* --radius */
#define TH_PAD      14
#define TH_GAP      10
#define TH_TAP_MIN  44     /* --tap: minimum touch target */

/* --- typography (Assistant == open twin of product B's Segoe UI) --- */
#define TH_FONT_SMALL  (&assistant_16)
#define TH_FONT_BODY   (&assistant_20)
#define TH_FONT_TITLE  (&assistant_28)
#define TH_FONT_H1     (&assistant_sb_28)
#define TH_FONT_CLOCK  (&assistant_sb_48)

/* Card base style helper. No shadow by design: shadow is a per-rect software
 * blur, and a 1px border reads just as cleanly on this flat, light UI. */
static inline void th_card(lv_obj_t *obj)
{
    lv_obj_set_style_bg_color(obj, TH_SURFACE, LV_PART_MAIN);
    lv_obj_set_style_radius(obj, TH_RADIUS, LV_PART_MAIN);
    lv_obj_set_style_border_width(obj, 1, LV_PART_MAIN);
    lv_obj_set_style_border_color(obj, TH_LINE, LV_PART_MAIN);
    lv_obj_set_style_pad_all(obj, TH_PAD, LV_PART_MAIN);
    lv_obj_set_style_shadow_width(obj, 0, LV_PART_MAIN);
}

/* Common screen base: bg, RTL, no free scrolling (hardware wants static
 * pages — see main.c Track A note). */
static inline void th_screen(lv_obj_t *scr)
{
    lv_obj_set_style_bg_color(scr, TH_BG, LV_PART_MAIN);
    lv_obj_set_style_base_dir(scr, LV_BASE_DIR_RTL, LV_PART_MAIN);
    lv_obj_remove_flag(scr, LV_OBJ_FLAG_SCROLLABLE);
}
