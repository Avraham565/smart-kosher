/* HomeScreen — product A wall panel.
 *
 * Layout (800x480, RTL):
 *   header 64px: brand title (right), clock + date (left)
 *   3 large nav cards: זמני היום / לוח שנה / הבית שלי
 * Data is placeholder until the hub link (UART) is wired.
 */

#include "ui_home.h"
#include "theme.h"

static lv_obj_t *s_status;

typedef struct {
    const char *title;
    const char *subtitle;
    lv_color_t accent;
} nav_card_def_t;

static const nav_card_def_t nav_cards[] = {
    { "זמני היום",  "19 זמנים להיום",        {} },
    { "לוח שנה",    "תאריך עברי ופרשה",     {} },
    { "הבית שלי",   "אזורים ומכשירים",      {} },
};

static void nav_card_cb(lv_event_t *e)
{
    int idx = (int)(intptr_t)lv_event_get_user_data(e);
    LV_LOG_USER("nav card %d clicked", idx);
    /* TODO: navigate to the target screen once it exists */
}

void ui_home_create(lv_display_t *disp)
{
    lv_obj_t *scr = lv_display_get_screen_active(disp);
    lv_obj_set_style_bg_color(scr, TH_BG, LV_PART_MAIN);
    lv_obj_set_style_base_dir(scr, LV_BASE_DIR_RTL, LV_PART_MAIN);
    lv_obj_remove_flag(scr, LV_OBJ_FLAG_SCROLLABLE);

    /* ---- header ---- */
    lv_obj_t *header = lv_obj_create(scr);
    lv_obj_set_size(header, LV_PCT(100), 64);
    lv_obj_set_pos(header, 0, 0);
    lv_obj_set_style_bg_color(header, TH_SURFACE, LV_PART_MAIN);
    lv_obj_set_style_radius(header, 0, LV_PART_MAIN);
    lv_obj_set_style_border_width(header, 0, LV_PART_MAIN);
    lv_obj_set_style_border_side(header, LV_BORDER_SIDE_BOTTOM, LV_PART_MAIN);
    lv_obj_set_style_pad_hor(header, 18, LV_PART_MAIN);
    lv_obj_set_style_pad_ver(header, 0, LV_PART_MAIN);
    lv_obj_remove_flag(header, LV_OBJ_FLAG_SCROLLABLE);

    lv_obj_t *brand = lv_label_create(header);
    lv_obj_set_style_text_font(brand, TH_FONT_H1, LV_PART_MAIN);
    lv_obj_set_style_text_color(brand, TH_TEXT, LV_PART_MAIN);
    lv_label_set_text(brand, "הבית החכם");
    lv_obj_align(brand, LV_ALIGN_RIGHT_MID, 0, 0);

    lv_obj_t *clock_label = lv_label_create(header);
    lv_obj_set_style_text_font(clock_label, TH_FONT_TITLE, LV_PART_MAIN);
    lv_obj_set_style_text_color(clock_label, TH_PRIMARY, LV_PART_MAIN);
    lv_label_set_text(clock_label, "--:--");
    lv_obj_align(clock_label, LV_ALIGN_LEFT_MID, 0, 0);

    lv_obj_t *date_label = lv_label_create(header);
    lv_obj_set_style_text_font(date_label, TH_FONT_SMALL, LV_PART_MAIN);
    lv_obj_set_style_text_color(date_label, TH_MUTED, LV_PART_MAIN);
    lv_label_set_text(date_label, "כ\"ג תמוז תשפ\"ו");
    lv_obj_align(date_label, LV_ALIGN_LEFT_MID, 96, 0);

    /* ---- nav cards ---- */
    lv_color_t accents[] = { TH_PRIMARY, TH_BLUE, TH_AMBER };
    const int CARD_W = 240, CARD_H = 300, GAP = 20;
    const int total = 3 * CARD_W + 2 * GAP;
    int x0 = (800 - total) / 2;

    for (int i = 0; i < 3; i++) {
        lv_obj_t *card = lv_obj_create(scr);
        th_card(card);
        lv_obj_set_size(card, CARD_W, CARD_H);
        /* RTL: first card on the right */
        lv_obj_set_pos(card, x0 + (2 - i) * (CARD_W + GAP), 110);
        lv_obj_remove_flag(card, LV_OBJ_FLAG_SCROLLABLE);
        lv_obj_add_flag(card, LV_OBJ_FLAG_CLICKABLE);
        lv_obj_set_style_bg_color(card, TH_SURFACE_STRONG,
                                  LV_PART_MAIN | LV_STATE_PRESSED);
        lv_obj_add_event_cb(card, nav_card_cb, LV_EVENT_CLICKED,
                            (void *)(intptr_t)i);

        lv_obj_t *stripe = lv_obj_create(card);
        lv_obj_set_size(stripe, 44, 6);
        lv_obj_set_style_bg_color(stripe, accents[i], LV_PART_MAIN);
        lv_obj_set_style_radius(stripe, 3, LV_PART_MAIN);
        lv_obj_set_style_border_width(stripe, 0, LV_PART_MAIN);
        lv_obj_align(stripe, LV_ALIGN_TOP_RIGHT, 0, 8);

        lv_obj_t *title = lv_label_create(card);
        lv_obj_set_style_text_font(title, TH_FONT_H1, LV_PART_MAIN);
        lv_obj_set_style_text_color(title, TH_TEXT, LV_PART_MAIN);
        lv_label_set_text(title, nav_cards[i].title);
        lv_obj_align(title, LV_ALIGN_TOP_RIGHT, 0, 44);

        lv_obj_t *sub = lv_label_create(card);
        lv_obj_set_style_text_font(sub, TH_FONT_BODY, LV_PART_MAIN);
        lv_obj_set_style_text_color(sub, TH_MUTED, LV_PART_MAIN);
        lv_label_set_text(sub, nav_cards[i].subtitle);
        lv_obj_align(sub, LV_ALIGN_TOP_RIGHT, 0, 88);
    }

    /* ---- footer status ---- */
    s_status = lv_label_create(scr);
    lv_obj_set_style_text_font(s_status, TH_FONT_SMALL, LV_PART_MAIN);
    lv_obj_set_style_text_color(s_status, TH_FAINT, LV_PART_MAIN);
    lv_label_set_text(s_status, "ממתין לחיבור למוח הבית…");
    lv_obj_align(s_status, LV_ALIGN_BOTTOM_MID, 0, -12);
}

void ui_home_set_status(const char *text, lv_color_t color)
{
    if (s_status == NULL) {
        return;
    }
    lv_label_set_text(s_status, text);
    lv_obj_set_style_text_color(s_status, color, LV_PART_MAIN);
    lv_obj_align(s_status, LV_ALIGN_BOTTOM_MID, 0, -12);
}
