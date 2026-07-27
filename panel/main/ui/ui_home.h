#pragma once

#include "lvgl.h"

void ui_home_create(lv_display_t *disp);

/* The home screen object, for detail screens that navigate back to it. */
lv_obj_t *ui_home_screen(void);

/* Update the footer status line (call with lvgl_port lock held). */
void ui_home_set_status(const char *text, lv_color_t color);
