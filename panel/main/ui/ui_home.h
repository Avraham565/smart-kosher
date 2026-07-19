#pragma once

#include "lvgl.h"

void ui_home_create(lv_display_t *disp);

/* Update the footer status line (call with lvgl_port lock held). */
void ui_home_set_status(const char *text, lv_color_t color);
