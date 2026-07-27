#include "shell.h"
#include "ui_home.h"
#include "clock.h"
#include "widgets.h"
#include "theme.h"

/* Corner clock on sub-pages: product decision still open. 1 = always-visible
 * time in the sub-page header (mockup showed it); 0 = title + back only. */
#define SHELL_CORNER_CLOCK 1

static void back_cb(lv_event_t *e)
{
    LV_UNUSED(e);
    lv_screen_load(ui_home_screen());   /* instant swap, no animation */
}

lv_obj_t *shell_page_create(const char *title, lv_obj_t **out_body)
{
    lv_obj_t *scr = lv_obj_create(NULL);
    th_screen(scr);

    /* ---- thin header (64px) ---- */
    lv_obj_t *header = w_header(scr, 64, 18);

    /* title — right edge (RTL reading start) */
    lv_obj_t *title_lbl = w_label(header, TH_FONT_H1, TH_TEXT, title);
    lv_obj_align(title_lbl, LV_ALIGN_RIGHT_MID, 0, 0);

    /* back button — left edge */
    lv_obj_t *back = lv_button_create(header);
    lv_obj_set_size(back, 100, TH_TAP_MIN);
    lv_obj_set_style_bg_color(back, TH_SURFACE_STRONG, LV_PART_MAIN);
    lv_obj_set_style_bg_color(back, TH_LINE, LV_PART_MAIN | LV_STATE_PRESSED);
    lv_obj_set_style_shadow_width(back, 0, LV_PART_MAIN);
    lv_obj_align(back, LV_ALIGN_LEFT_MID, 0, 0);
    lv_obj_add_event_cb(back, back_cb, LV_EVENT_CLICKED, NULL);
    lv_obj_center(w_label(back, TH_FONT_BODY, TH_TEXT, "› חזרה"));

#if SHELL_CORNER_CLOCK
    lv_obj_t *mini = w_label(header, TH_FONT_BODY, TH_MUTED, "");
    lv_obj_align(mini, LV_ALIGN_LEFT_MID, 116, 0);   /* just right of back */
    clock_bind_time(mini);
#endif

    /* ---- body ---- */
    lv_obj_t *body = lv_obj_create(scr);
    lv_obj_set_size(body, LV_PCT(100), 480 - 64);
    lv_obj_set_pos(body, 0, 64);
    lv_obj_set_style_bg_opa(body, LV_OPA_TRANSP, LV_PART_MAIN);
    lv_obj_set_style_border_width(body, 0, LV_PART_MAIN);
    lv_obj_set_style_pad_all(body, 24, LV_PART_MAIN);
    lv_obj_remove_flag(body, LV_OBJ_FLAG_SCROLLABLE);

    if (out_body) {
        *out_body = body;
    }
    return scr;
}

lv_obj_t *shell_placeholder(const char *title, const char *subtitle,
                            lv_color_t accent)
{
    lv_obj_t *body;
    lv_obj_t *scr = shell_page_create(title, &body);

    lv_obj_align(w_stripe(body, 56, accent), LV_ALIGN_CENTER, 0, -44);
    lv_obj_align(w_label(body, TH_FONT_TITLE, TH_TEXT, subtitle),
                 LV_ALIGN_CENTER, 0, 0);
    lv_obj_align(w_label(body, TH_FONT_BODY, TH_FAINT, "המסך בבנייה"),
                 LV_ALIGN_CENTER, 0, 44);
    return scr;
}
