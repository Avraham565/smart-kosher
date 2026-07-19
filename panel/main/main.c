/*
 * Panel A — CrowPanel Advance 7" (ESP32-S3) UI firmware.
 *
 * Built strictly from official documentation:
 *   - esp_lcd RGB panel (Espressif): 2 PSRAM frame buffers + bounce buffers,
 *     the documented mitigation for RGB "screen drift"
 *     https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-reference/peripherals/lcd/rgb_lcd.html
 *   - esp_lvgl_port (Espressif): LVGL glue with avoid_tearing + bb_mode
 *   - Timings: Elecrow factory example (LovyanGFX_Driver.h in the official
 *     CrowPanel-Advance-7 repo): 21 MHz pclk, porches 8/4/8, clock edge
 *     equal to esp_lcd pclk_active_neg=1.
 *
 * Hardware map (validated on this exact board during MicroPython bring-up):
 *   RGB  B0-B4: 21,47,48,45,38   G0-G5: 9,10,11,12,13,14   R0-R4: 7,17,18,3,46
 *   HSYNC=40 VSYNC=41 DE=42 PCLK=39
 *   I2C0: SDA=15 SCL=16 — GT911 touch @0x5D, backlight expander @0x30 (bit 1)
 */

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/i2c_master.h"
#include "esp_lcd_panel_ops.h"
#include "esp_lcd_panel_rgb.h"
#include "esp_lcd_touch_gt911.h"
#include "esp_lcd_panel_io.h"
#include "esp_lvgl_port.h"
#include "esp_log.h"
#include "lvgl.h"
#include "fonts/fonts.h"

static const char *TAG = "panel_a";

#define LCD_H_RES 800
#define LCD_V_RES 480
#define LCD_PCLK_HZ (21 * 1000 * 1000)   /* Elecrow factory value */
#define BOUNCE_LINES 10                  /* 800*10*2 = 16KB x2 internal RAM */

#define PIN_HSYNC 40
#define PIN_VSYNC 41
#define PIN_DE 42
#define PIN_PCLK 39

#define I2C_SDA 15
#define I2C_SCL 16
#define BL_ADDR 0x30
#define BL_BIT 1

static i2c_master_bus_handle_t s_i2c_bus;

/* ------------------------------------------------------------------ */
/* Backlight: STC8H1K28 expander, TCA9534-style registers              */
/* (reg 3 = config, 0x00 -> all outputs; reg 1 = output latch)         */
/* ------------------------------------------------------------------ */
static void backlight_on(void)
{
    i2c_device_config_t cfg = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7,
        .device_address = BL_ADDR,
        .scl_speed_hz = 400000,
    };
    i2c_master_dev_handle_t dev;
    ESP_ERROR_CHECK(i2c_master_bus_add_device(s_i2c_bus, &cfg, &dev));

    uint8_t config_all_outputs[] = { 0x03, 0x00 };
    uint8_t set_bl_bit[] = { 0x01, (uint8_t)(1u << BL_BIT) };
    ESP_ERROR_CHECK(i2c_master_transmit(dev, config_all_outputs, 2, 100));
    ESP_ERROR_CHECK(i2c_master_transmit(dev, set_bl_bit, 2, 100));
    ESP_LOGI(TAG, "backlight on");
}

/* ------------------------------------------------------------------ */
/* RGB LCD panel                                                       */
/* ------------------------------------------------------------------ */
static esp_lcd_panel_handle_t init_rgb_panel(void)
{
    esp_lcd_rgb_panel_config_t cfg = {
        .clk_src = LCD_CLK_SRC_DEFAULT,
        .timings = {
            .pclk_hz = LCD_PCLK_HZ,
            .h_res = LCD_H_RES,
            .v_res = LCD_V_RES,
            .hsync_front_porch = 8,
            .hsync_back_porch = 8,
            .hsync_pulse_width = 4,
            .vsync_front_porch = 8,
            .vsync_back_porch = 8,
            .vsync_pulse_width = 4,
            .flags = {
                /* Elecrow factory: hsync/vsync/de polarity 0, clock edge 1 */
                .hsync_idle_low = 0,
                .vsync_idle_low = 0,
                .de_idle_high = 0,
                .pclk_active_neg = 1,
                .pclk_idle_high = 0,
            },
        },
        .data_width = 16,
        .bits_per_pixel = 16,
        .num_fbs = 2,                                   /* double FB in PSRAM */
        .bounce_buffer_size_px = LCD_H_RES * BOUNCE_LINES,
        .hsync_gpio_num = PIN_HSYNC,
        .vsync_gpio_num = PIN_VSYNC,
        .de_gpio_num = PIN_DE,
        .pclk_gpio_num = PIN_PCLK,
        .disp_gpio_num = -1,
        .data_gpio_nums = {
            21, 47, 48, 45, 38,        /* B0-B4  */
            9, 10, 11, 12, 13, 14,     /* G0-G5  */
            7, 17, 18, 3, 46,          /* R0-R4  */
        },
        .flags = {
            .fb_in_psram = 1,
        },
    };

    esp_lcd_panel_handle_t panel;
    ESP_ERROR_CHECK(esp_lcd_new_rgb_panel(&cfg, &panel));
    ESP_ERROR_CHECK(esp_lcd_panel_reset(panel));
    ESP_ERROR_CHECK(esp_lcd_panel_init(panel));
    ESP_LOGI(TAG, "RGB panel up (%d MHz, bounce %d lines)",
             LCD_PCLK_HZ / 1000000, BOUNCE_LINES);
    return panel;
}

/* ------------------------------------------------------------------ */
/* GT911 touch                                                         */
/* ------------------------------------------------------------------ */
static esp_lcd_touch_handle_t init_touch(void)
{
    esp_lcd_panel_io_handle_t io = NULL;
    esp_lcd_panel_io_i2c_config_t io_cfg = ESP_LCD_TOUCH_IO_I2C_GT911_CONFIG();
    io_cfg.scl_speed_hz = 400000;
    ESP_ERROR_CHECK(esp_lcd_new_panel_io_i2c(s_i2c_bus, &io_cfg, &io));

    esp_lcd_touch_config_t tp_cfg = {
        .x_max = LCD_H_RES,
        .y_max = LCD_V_RES,
        .rst_gpio_num = -1,   /* not wired on CrowPanel */
        .int_gpio_num = -1,
    };
    esp_lcd_touch_handle_t tp = NULL;
    ESP_ERROR_CHECK(esp_lcd_touch_new_i2c_gt911(io, &tp_cfg, &tp));
    ESP_LOGI(TAG, "GT911 touch up");
    return tp;
}

/* ------------------------------------------------------------------ */
/* Hebrew hello screen (validation UI, mirrors the MicroPython probe)  */
/* ------------------------------------------------------------------ */
static void button_cb(lv_event_t *e)
{
    static int clicks = 0;
    lv_obj_t *label = lv_event_get_user_data(e);
    lv_label_set_text_fmt(label, "נלחץ! %d", ++clicks);
}

static void build_ui(lv_display_t *disp)
{
    lvgl_port_lock(0);

    lv_obj_t *scr = lv_display_get_screen_active(disp);
    lv_obj_set_style_bg_color(scr, lv_color_hex(0x0D0D1A), LV_PART_MAIN);
    lv_obj_set_style_base_dir(scr, LV_BASE_DIR_RTL, LV_PART_MAIN);
    lv_obj_remove_flag(scr, LV_OBJ_FLAG_SCROLLABLE);

    const lv_font_t *heb = &assistant_20;

    lv_obj_t *title = lv_label_create(scr);
    lv_obj_set_style_text_font(title, &assistant_sb_28, LV_PART_MAIN);
    lv_obj_set_style_text_color(title, lv_color_hex(0xFFFFFF), LV_PART_MAIN);
    lv_label_set_text(title, "שלום עולם — פאנל C לפי תיעוד רשמי");
    lv_obj_align(title, LV_ALIGN_TOP_MID, 0, 14);

    lv_obj_t *mixed = lv_label_create(scr);
    lv_obj_set_style_text_font(mixed, heb, LV_PART_MAIN);
    lv_obj_set_style_text_color(mixed, lv_color_hex(0x7EC8E3), LV_PART_MAIN);
    lv_label_set_text(mixed, "3 דולקים מתוך 5 מכשירים");
    lv_obj_align(mixed, LV_ALIGN_TOP_MID, 0, 46);

    /* RTL scrollable device list — the exact scenario that broke MicroPython */
    lv_obj_t *panel = lv_obj_create(scr);
    lv_obj_set_size(panel, 720, 270);
    lv_obj_set_pos(panel, 40, 84);
    lv_obj_set_style_bg_color(panel, lv_color_hex(0x0A0A14), LV_PART_MAIN);
    lv_obj_set_style_border_width(panel, 0, LV_PART_MAIN);
    lv_obj_set_style_radius(panel, 12, LV_PART_MAIN);
    lv_obj_set_flex_flow(panel, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_scroll_dir(panel, LV_DIR_VER);

    static const char *names[] = {
        "דוד שמש", "מזגן סלון", "תאורת חדר מדרגות", "פלטת שבת",
        "מיחם", "מזגן חדר שינה", "תאורת חצר", "ונטה אמבטיה",
    };
    for (int i = 0; i < 8; i++) {
        lv_obj_t *row = lv_obj_create(panel);
        lv_obj_set_size(row, LV_PCT(100), 56);
        lv_obj_set_style_bg_color(row, lv_color_hex(0x16213E), LV_PART_MAIN);
        lv_obj_set_style_border_width(row, 0, LV_PART_MAIN);
        lv_obj_set_style_radius(row, 10, LV_PART_MAIN);
        lv_obj_remove_flag(row, LV_OBJ_FLAG_SCROLLABLE);

        lv_obj_t *name = lv_label_create(row);
        lv_obj_set_style_text_font(name, heb, LV_PART_MAIN);
        lv_obj_set_style_text_color(name, lv_color_hex(0xEEEEEE), LV_PART_MAIN);
        lv_label_set_text(name, names[i]);
        lv_obj_align(name, LV_ALIGN_RIGHT_MID, 0, 0);

        lv_obj_t *state = lv_label_create(row);
        lv_obj_set_style_text_font(state, heb, LV_PART_MAIN);
        bool on = (i % 2) == 0;
        lv_obj_set_style_text_color(
            state, lv_color_hex(on ? 0xFFB300 : 0x667788), LV_PART_MAIN);
        lv_label_set_text(state, on ? "דולק" : "כבוי");
        lv_obj_align(state, LV_ALIGN_LEFT_MID, 0, 0);
    }

    lv_obj_t *btn = lv_button_create(scr);
    lv_obj_set_size(btn, 220, 72);
    lv_obj_align(btn, LV_ALIGN_BOTTOM_MID, 0, -20);
    lv_obj_set_style_bg_color(btn, lv_color_hex(0x0F3460), LV_PART_MAIN);
    lv_obj_t *btn_label = lv_label_create(btn);
    lv_obj_set_style_text_font(btn_label, heb, LV_PART_MAIN);
    lv_label_set_text(btn_label, "לחץ עליי");
    lv_obj_center(btn_label);
    lv_obj_add_event_cb(btn, button_cb, LV_EVENT_CLICKED, btn_label);

    lvgl_port_unlock();
}

void app_main(void)
{
    i2c_master_bus_config_t bus_cfg = {
        .i2c_port = 0,
        .sda_io_num = I2C_SDA,
        .scl_io_num = I2C_SCL,
        .clk_source = I2C_CLK_SRC_DEFAULT,
        .glitch_ignore_cnt = 7,
        .flags.enable_internal_pullup = true,
    };
    ESP_ERROR_CHECK(i2c_new_master_bus(&bus_cfg, &s_i2c_bus));

    backlight_on();
    esp_lcd_panel_handle_t panel = init_rgb_panel();
    esp_lcd_touch_handle_t touch = init_touch();

    /* Default affinity: pinning LVGL to core 1 while the panel ISRs live on
     * core 0 corrupted scrolling in direct mode — keep them together. */
    const lvgl_port_cfg_t port_cfg = ESP_LVGL_PORT_INIT_CONFIG();
    ESP_ERROR_CHECK(lvgl_port_init(&port_cfg));

    const lvgl_port_display_cfg_t disp_cfg = {
        .panel_handle = panel,
        .buffer_size = LCD_H_RES * LCD_V_RES,
        .double_buffer = true,
        .hres = LCD_H_RES,
        .vres = LCD_V_RES,
        .color_format = LV_COLOR_FORMAT_RGB565,
        .flags = {
            .buff_dma = false,
            .buff_spiram = false,
            .direct_mode = true,   /* draw into the panel FBs directly */
            .swap_bytes = false,
        },
    };
    const lvgl_port_display_rgb_cfg_t rgb_cfg = {
        .flags = {
            .bb_mode = true,        /* we allocated bounce buffers */
            .avoid_tearing = true,  /* LVGL draws into the 2 panel FBs */
        },
    };
    lv_display_t *disp = lvgl_port_add_disp_rgb(&disp_cfg, &rgb_cfg);
    assert(disp != NULL);

    const lvgl_port_touch_cfg_t touch_cfg = {
        .disp = disp,
        .handle = touch,
    };
    lvgl_port_add_touch(&touch_cfg);

    build_ui(disp);
    ESP_LOGI(TAG, "UI up — LVGL %d.%d", lv_version_major(), lv_version_minor());
}
