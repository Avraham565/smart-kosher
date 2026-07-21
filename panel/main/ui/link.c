#include "link.h"

#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/uart.h"
#include "esp_log.h"
#include "esp_lvgl_port.h"
#include "soc/usb_serial_jtag_reg.h"
#include "soc/soc.h"

#include "theme.h"
#include "ui_home.h"

static const char *TAG = "link";

#define LINK_UART UART_NUM_1
#define LINK_TX_PIN 20        /* UART1-OUT: IO20-TX1 */
#define LINK_RX_PIN 19        /* UART1-OUT: IO19-RX1 */
#define LINK_BAUD 115200
#define RX_BUF_SIZE 2048

/* One send/receive round. Returns true when our frame came back intact. */
static bool loop_round(uint32_t seq)
{
    char tx_frame[32];
    uint8_t rx_buf[64];

    int len = snprintf(tx_frame, sizeof(tx_frame), "SKLOOP %lu\n",
                       (unsigned long)seq);
    uart_flush_input(LINK_UART);
    uart_write_bytes(LINK_UART, tx_frame, len);

    int got = uart_read_bytes(LINK_UART, rx_buf, len, pdMS_TO_TICKS(200));
    return got == len && memcmp(rx_buf, tx_frame, len) == 0;
}

static void link_task(void *arg)
{
    uint32_t seq = 0;
    int ok_streak = 0;
    bool reported_ok = false;

    /* Phase 0 — the test tests itself: internal loopback inside the chip,
     * no wiring involved. Proves driver + framing code end-to-end. */
    ESP_ERROR_CHECK(uart_set_loop_back(LINK_UART, true));
    bool self_ok = false;
    for (int i = 0; i < 5 && !self_ok; i++) {
        self_ok = loop_round(++seq);
    }
    ESP_ERROR_CHECK(uart_set_loop_back(LINK_UART, false));
    ESP_LOGI(TAG, "internal self-test: %s", self_ok ? "PASS" : "FAIL");

    lvgl_port_lock(0);
    if (self_ok) {
        ui_home_set_status("ממתין לחיבור למוח הבית…", TH_BLUE);
    } else {
        ui_home_set_status("✗ בדיקה עצמית נכשלה — באג בקוד הקו", TH_DANGER);
    }
    lvgl_port_unlock();

    while (true) {
        bool echoed = loop_round(++seq);

        if (echoed) {
            ok_streak++;
            if (ok_streak >= 3 && !reported_ok) {
                reported_ok = true;
                ESP_LOGI(TAG, "hub link up (streak %d)", ok_streak);
                lvgl_port_lock(0);
                ui_home_set_status("✓ מחובר למוח הבית", TH_SUCCESS);
                lvgl_port_unlock();
            }
        } else {
            if (reported_ok || ok_streak > 0) {
                ESP_LOGI(TAG, "hub link lost");
            }
            ok_streak = 0;
            if (reported_ok) {
                reported_ok = false;
                lvgl_port_lock(0);
                ui_home_set_status("החיבור למוח הבית נותק", TH_AMBER);
                lvgl_port_unlock();
            }
        }
        vTaskDelay(pdMS_TO_TICKS(500));
    }
}

void link_init(void)
{
    /* GPIO19/20 are the S3's native USB D-/D+ pads. The CrowPanel routes
     * them to UART1-OUT instead (console is on the CH340), but the
     * USB-Serial-JTAG peripheral claims the pads by default — release
     * them so the UART matrix owns the pins cleanly. */
    CLEAR_PERI_REG_MASK(USB_SERIAL_JTAG_CONF0_REG,
                        USB_SERIAL_JTAG_USB_PAD_ENABLE);

    const uart_config_t cfg = {
        .baud_rate = LINK_BAUD,
        .data_bits = UART_DATA_8_BITS,
        .parity = UART_PARITY_DISABLE,
        .stop_bits = UART_STOP_BITS_1,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
        .source_clk = UART_SCLK_DEFAULT,
    };
    ESP_ERROR_CHECK(uart_driver_install(LINK_UART, RX_BUF_SIZE, 0, 0, NULL, 0));
    ESP_ERROR_CHECK(uart_param_config(LINK_UART, &cfg));
    ESP_ERROR_CHECK(uart_set_pin(LINK_UART, LINK_TX_PIN, LINK_RX_PIN,
                                 UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE));

    lvgl_port_lock(0);
    ui_home_set_status("בדיקת קו: חבר גשר בין TX1 ל-RX1 במחבר UART1-OUT",
                       TH_AMBER);
    lvgl_port_unlock();

    xTaskCreate(link_task, "link", 4096, NULL, 5, NULL);
    ESP_LOGI(TAG, "UART1 up: TX=%d RX=%d @%d", LINK_TX_PIN, LINK_RX_PIN,
             LINK_BAUD);
}
