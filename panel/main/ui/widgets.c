#include "widgets.h"
#include "theme.h"

lv_obj_t *w_label(lv_obj_t *parent, const lv_font_t *font,
                  lv_color_t color, const char *text)
{
    lv_obj_t *l = lv_label_create(parent);
    lv_obj_set_style_text_font(l, font, LV_PART_MAIN);
    lv_obj_set_style_text_color(l, color, LV_PART_MAIN);
    lv_label_set_text(l, text);
    return l;
}

lv_obj_t *w_group(lv_obj_t *parent, lv_flex_flow_t flow)
{
    lv_obj_t *g = lv_obj_create(parent);
    lv_obj_set_size(g, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
    lv_obj_set_style_bg_opa(g, LV_OPA_TRANSP, LV_PART_MAIN);
    lv_obj_set_style_border_width(g, 0, LV_PART_MAIN);
    lv_obj_set_style_pad_all(g, 0, LV_PART_MAIN);
    lv_obj_remove_flag(g, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_flex_flow(g, flow);
    return g;
}

lv_obj_t *w_stripe(lv_obj_t *parent, int width, lv_color_t color)
{
    lv_obj_t *s = lv_obj_create(parent);
    lv_obj_set_size(s, width, 6);
    lv_obj_set_style_bg_color(s, color, LV_PART_MAIN);
    lv_obj_set_style_radius(s, 3, LV_PART_MAIN);
    lv_obj_set_style_border_width(s, 0, LV_PART_MAIN);
    return s;
}

lv_obj_t *w_header(lv_obj_t *parent, int height, int pad_hor)
{
    lv_obj_t *h = lv_obj_create(parent);
    lv_obj_set_size(h, LV_PCT(100), height);
    lv_obj_set_pos(h, 0, 0);
    lv_obj_set_style_bg_color(h, TH_SURFACE, LV_PART_MAIN);
    lv_obj_set_style_radius(h, 0, LV_PART_MAIN);
    lv_obj_set_style_border_width(h, 1, LV_PART_MAIN);
    lv_obj_set_style_border_side(h, LV_BORDER_SIDE_BOTTOM, LV_PART_MAIN);
    lv_obj_set_style_border_color(h, TH_LINE, LV_PART_MAIN);
    lv_obj_set_style_pad_hor(h, pad_hor, LV_PART_MAIN);
    lv_obj_set_style_pad_ver(h, 0, LV_PART_MAIN);
    lv_obj_remove_flag(h, LV_OBJ_FLAG_SCROLLABLE);
    return h;
}

lv_obj_t *w_card_button(lv_obj_t *parent)
{
    lv_obj_t *card = lv_obj_create(parent);
    th_card(card);
    lv_obj_remove_flag(card, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_add_flag(card, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_set_style_bg_color(card, TH_SURFACE_STRONG,
                              LV_PART_MAIN | LV_STATE_PRESSED);
    return card;
}
