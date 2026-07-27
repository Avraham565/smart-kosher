/* HomeScreen — product A wall panel (the idle "wall clock" face).
 *
 * Layout (800x480, RTL), all static — no scroll, no animation (Track A):
 *   header 110px: logo (right) · clock + Hebrew/Gregorian date (left)
 *   body: hero button "הבית שלי" + a row of 4 (תזמונים / זמני הלכה /
 *         לוח שנה / יציאה מהבית), all driven by the page registry
 *   footer 34px: hub-link status line
 *
 * The arrangement (hero + 4) lives here and only here — page.c stays neutral.
 * Screens are built from the widgets.h component vocabulary. Clock/date are
 * mock scaffolding (see clock.c); tapping the clock opens a placeholder.
 */

#include "ui_home.h"
#include "shell.h"
#include "page.h"
#include "clock.h"
#include "widgets.h"
#include "theme.h"

static lv_obj_t *s_screen;
static lv_obj_t *s_status;
static lv_obj_t *s_settime;   /* lazily-built time/date screen */

/* ------------------------------------------------------------------ */
/* navigation                                                          */
/* ------------------------------------------------------------------ */
static void nav_cb(lv_event_t *e)
{
    page_open((page_id_t)(intptr_t)lv_event_get_user_data(e));
}

static void settime_cb(lv_event_t *e)
{
    LV_UNUSED(e);
    if (s_settime == NULL) {
        s_settime = shell_placeholder("כיוון שעה ותאריך",
                                      "שעה ותאריך", TH_PRIMARY);
    }
    lv_screen_load(s_settime);
}

/* ------------------------------------------------------------------ */
/* header                                                              */
/* ------------------------------------------------------------------ */
static void build_brand(lv_obj_t *header)
{
    lv_obj_t *cluster = w_group(header, LV_FLEX_FLOW_ROW);
    lv_obj_set_flex_align(cluster, LV_FLEX_ALIGN_START,
                          LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_column(cluster, 12, LV_PART_MAIN);
    lv_obj_align(cluster, LV_ALIGN_RIGHT_MID, 0, 0);

    /* logo mark — placeholder (solid primary + house glyph) until a real
     * asset is decided (image vs wordmark). RTL: sits at the right. */
    lv_obj_t *mark = lv_obj_create(cluster);
    lv_obj_set_size(mark, 52, 52);
    lv_obj_set_style_bg_color(mark, TH_PRIMARY, LV_PART_MAIN);
    lv_obj_set_style_radius(mark, 12, LV_PART_MAIN);
    lv_obj_set_style_border_width(mark, 0, LV_PART_MAIN);
    lv_obj_set_style_pad_all(mark, 0, LV_PART_MAIN);
    lv_obj_remove_flag(mark, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_center(w_label(mark, &lv_font_montserrat_28, TH_SURFACE,
                          LV_SYMBOL_HOME));

    /* wordmark */
    lv_obj_t *words = w_group(cluster, LV_FLEX_FLOW_COLUMN);
    w_label(words, TH_FONT_H1, TH_TEXT, "סמארט אנד כשר");
    lv_obj_t *en = w_label(words, TH_FONT_SMALL, TH_FAINT, "Smart & Kosher");
    lv_obj_set_style_base_dir(en, LV_BASE_DIR_LTR, LV_PART_MAIN);
}

static void build_timeblock(lv_obj_t *header)
{
    lv_obj_t *cluster = w_group(header, LV_FLEX_FLOW_ROW);
    lv_obj_set_style_pad_all(cluster, 4, LV_PART_MAIN);   /* tap target */
    lv_obj_set_flex_align(cluster, LV_FLEX_ALIGN_START,
                          LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_column(cluster, 16, LV_PART_MAIN);
    lv_obj_align(cluster, LV_ALIGN_LEFT_MID, 0, 0);
    lv_obj_add_flag(cluster, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_add_event_cb(cluster, settime_cb, LV_EVENT_CLICKED, NULL);

    /* dates (right of the clock, toward centre) */
    lv_obj_t *dates = w_group(cluster, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_style_pad_row(dates, 2, LV_PART_MAIN);

    /* Hebrew line: day-of-week (primary) + rest (text) */
    lv_obj_t *heb = w_group(dates, LV_FLEX_FLOW_ROW);
    lv_obj_set_style_pad_column(heb, 6, LV_PART_MAIN);
    w_label(heb, TH_FONT_BODY, TH_PRIMARY, clock_date_hebrew_dow());
    lv_obj_t *hdate = w_label(heb, TH_FONT_BODY, TH_TEXT, "");
    lv_label_set_text_fmt(hdate, "· %s", clock_date_hebrew());

    lv_obj_t *greg = w_label(dates, TH_FONT_SMALL, TH_MUTED,
                             clock_date_gregorian());
    lv_obj_set_style_base_dir(greg, LV_BASE_DIR_LTR, LV_PART_MAIN);

    /* the clock itself — left edge */
    clock_bind_time(w_label(cluster, TH_FONT_CLOCK, TH_TEXT, ""));
}

/* ------------------------------------------------------------------ */
/* nav cards                                                           */
/* ------------------------------------------------------------------ */
/* Hero card — wide, right-aligned content, primary stripe. */
static void build_hero(lv_obj_t *body)
{
    const page_def_t *def = page_def(PAGE_HOUSE);
    lv_obj_t *card = w_card_button(body);
    lv_obj_set_width(card, LV_PCT(100));
    lv_obj_set_flex_grow(card, 3);
    lv_obj_add_event_cb(card, nav_cb, LV_EVENT_CLICKED,
                        (void *)(intptr_t)PAGE_HOUSE);

    lv_obj_align(w_stripe(card, 56, lv_color_hex(def->accent)),
                 LV_ALIGN_TOP_RIGHT, 0, 4);
    lv_obj_align(w_label(card, TH_FONT_TITLE, TH_TEXT, def->title),
                 LV_ALIGN_RIGHT_MID, 0, -6);
    lv_obj_align(w_label(card, TH_FONT_BODY, TH_MUTED, def->subtitle),
                 LV_ALIGN_RIGHT_MID, 0, 30);
}

/* One small card in the row of four. */
static void build_navcard(lv_obj_t *row, page_id_t id)
{
    const page_def_t *def = page_def(id);
    lv_obj_t *card = w_card_button(row);
    lv_obj_set_height(card, LV_PCT(100));
    lv_obj_set_flex_grow(card, 1);
    lv_obj_set_flex_flow(card, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(card, LV_FLEX_ALIGN_CENTER,
                          LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_row(card, 10, LV_PART_MAIN);
    lv_obj_add_event_cb(card, nav_cb, LV_EVENT_CLICKED, (void *)(intptr_t)id);

    w_stripe(card, 40, lv_color_hex(def->accent));
    w_label(card, TH_FONT_H1, TH_TEXT, def->title);
}

/* ------------------------------------------------------------------ */
/* public                                                              */
/* ------------------------------------------------------------------ */
lv_obj_t *ui_home_screen(void)
{
    return s_screen;
}

void ui_home_create(lv_display_t *disp)
{
    lv_obj_t *scr = lv_display_get_screen_active(disp);
    s_screen = scr;
    th_screen(scr);

    /* ---- header ---- */
    lv_obj_t *header = w_header(scr, 110, 26);
    build_brand(header);
    build_timeblock(header);

    /* ---- body: hero + row of four ---- */
    lv_obj_t *body = lv_obj_create(scr);
    lv_obj_set_size(body, LV_PCT(100), 336);
    lv_obj_set_pos(body, 0, 110);
    lv_obj_set_style_bg_opa(body, LV_OPA_TRANSP, LV_PART_MAIN);
    lv_obj_set_style_border_width(body, 0, LV_PART_MAIN);
    lv_obj_set_style_pad_all(body, 18, LV_PART_MAIN);
    lv_obj_remove_flag(body, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_flex_flow(body, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_style_pad_row(body, 14, LV_PART_MAIN);

    build_hero(body);

    lv_obj_t *row = w_group(body, LV_FLEX_FLOW_ROW);
    lv_obj_set_width(row, LV_PCT(100));
    lv_obj_set_flex_grow(row, 2);
    lv_obj_set_style_pad_column(row, 14, LV_PART_MAIN);
    build_navcard(row, PAGE_SCHEDULES);
    build_navcard(row, PAGE_ZMANIM);
    build_navcard(row, PAGE_CALENDAR);
    build_navcard(row, PAGE_AWAY);

    /* ---- footer status ---- */
    s_status = w_label(scr, TH_FONT_SMALL, TH_FAINT, "ממתין לחיבור למוח הבית…");
    lv_obj_align(s_status, LV_ALIGN_BOTTOM_MID, 0, -10);

    clock_start();
}

void ui_home_set_status(const char *text, lv_color_t color)
{
    if (s_status == NULL) {
        return;
    }
    lv_label_set_text(s_status, text);
    lv_obj_set_style_text_color(s_status, color, LV_PART_MAIN);
    lv_obj_align(s_status, LV_ALIGN_BOTTOM_MID, 0, -10);
}
