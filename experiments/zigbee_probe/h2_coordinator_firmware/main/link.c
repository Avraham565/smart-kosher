#include "link.h"

#include <inttypes.h>
#include <stdio.h>
#include <string.h>

#include "driver/uart.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "sdkconfig.h"

#include "protocol.h"

#define TAG "H2_LINK"

#define UART_PORT ((uart_port_t)CONFIG_COORD_UART_PORT)

/* ~2.6 s of wire at 115200: enough that a busy consumer on either side cannot
 * make the driver drop bytes underneath us. */
#define RX_DRIVER_BUF 4096
/* Non-zero, unlike the original: with a 0-size TX buffer uart_write_bytes
 * blocks until the FIFO drains, and it used to be called from Zigbee stack
 * callbacks. Now only the TX task writes, and it does not stall either. */
#define TX_DRIVER_BUF 2048

/* Deep enough to absorb the hub retrying reporting for every child at once
 * (max_children = 10) without rejecting any. */
#define RX_QUEUE_DEPTH 12
#define TX_QUEUE_DEPTH 8

/* The two directions are not symmetric, and sizing them alike wasted memory:
 * inbound commands are small (the largest, remove_device with an IEEE address,
 * is under 200 bytes) while an outbound ping ack carries the capability list
 * and eleven counters. */
#define RX_ITEM_MAX 320
#define TX_ITEM_MAX PROTO_MAX_LINE

typedef struct { char body[RX_ITEM_MAX]; } rx_item_t;
typedef struct { char body[TX_ITEM_MAX]; } tx_item_t;

static QueueHandle_t s_rx_q;
static QueueHandle_t s_tx_q;
static link_stats_t  s_stats;

const link_stats_t *link_stats(void) { return &s_stats; }

void link_send_body(const char *body)
{
    if (s_tx_q == NULL || body == NULL) return;

    /* On the stack, not static: this is called from several tasks (and from
     * Zigbee stack callbacks), and a shared staging buffer would interleave
     * two frames into one. Every task that can reach here is created with a
     * stack that comfortably absorbs one item. */
    tx_item_t item;
    int written = snprintf(item.body, sizeof(item.body), "%s", body);
    if (written < 0 || (size_t)written >= sizeof(item.body)) {
        /* Never put a truncated body on the wire: it would carry a perfectly
         * valid CRC over invalid JSON, so the hub would reject a frame that
         * looks intact and the fault would appear to be the link. */
        s_stats.tx_oversize_drops++;
        ESP_LOGE(TAG, "frame too long (%d bytes), dropped", written);
        return;
    }
    if (xQueueSend(s_tx_q, &item, 0) != pdTRUE) {
        s_stats.tx_queue_drops++;
        return;
    }
    uint32_t waiting = (uint32_t)uxQueueMessagesWaiting(s_tx_q);
    if (waiting > s_stats.tx_peak) s_stats.tx_peak = waiting;
}

bool link_take_command(char *out, size_t out_len, uint32_t wait_ticks)
{
    if (s_rx_q == NULL) return false;
    rx_item_t item;
    if (xQueueReceive(s_rx_q, &item, wait_ticks) != pdTRUE) return false;
    snprintf(out, out_len, "%s", item.body);
    return true;
}

/* Small fixed-shape frames, built without cJSON so this layer stays free of
 * it: a link-level complaint must not depend on the payload layer. */
static void send_link_error(const char *code)
{
    char body[128];
    snprintf(body, sizeof(body),
             "{\"version\":1,\"type\":\"error\",\"payload\":"
             "{\"code\":\"%s\",\"message\":\"\"}}", code);
    link_send_body(body);
}

static void handle_line(char *line)
{
    const char *body = NULL;
    switch (proto_frame_body(line, &body)) {
    case PROTO_FRAME_OK:
        break;
    case PROTO_FRAME_BAD_CRC:
        s_stats.crc_errors++;
        send_link_error("bad_crc");
        return;
    case PROTO_FRAME_BAD_PREFIX:
    default:
        /* The original returned silently here, so a mangled command looked
         * exactly like silence and the sender waited out its full timeout. */
        s_stats.prefix_errors++;
        send_link_error("bad_frame");
        return;
    }

    rx_item_t item;
    int written = snprintf(item.body, sizeof(item.body), "%s", body);
    if (written < 0 || (size_t)written >= sizeof(item.body)) {
        /* Same rule as outbound: never hand on a half a command. Say so, so a
         * command that outgrows this is a visible error and not a mystery. */
        s_stats.rx_oversize_drops++;
        send_link_error("frame_too_long");
        return;
    }
    if (xQueueSend(s_rx_q, &item, 0) != pdTRUE) {
        s_stats.rx_queue_drops++;
        send_link_error("busy");
        return;
    }
    s_stats.rx_frames++;
}

static void rx_task(void *arg)
{
    (void)arg;
    static proto_lines_t lines;
    uint8_t buf[128];

    proto_lines_init(&lines);
    for (;;) {
        int n = uart_read_bytes(UART_PORT, buf, sizeof(buf), pdMS_TO_TICKS(50));
        for (int i = 0; i < n; i++) {
            if (proto_lines_feed(&lines, (char)buf[i], &s_stats.rx_line_drops)) {
                handle_line(lines.buf);
            }
        }
    }
}

static void tx_task(void *arg)
{
    (void)arg;
    tx_item_t item;
    char prefix[16];

    for (;;) {
        if (xQueueReceive(s_tx_q, &item, portMAX_DELAY) != pdTRUE) continue;
        size_t len = strlen(item.body);
        int n = snprintf(prefix, sizeof(prefix), "%08" PRIx32 " ",
                         proto_crc32(item.body, len));
        uart_write_bytes(UART_PORT, prefix, n);
        uart_write_bytes(UART_PORT, item.body, len);
        uart_write_bytes(UART_PORT, "\n", 1);
    }
}

void link_start(void)
{
    const uart_config_t cfg = {
        .baud_rate  = CONFIG_COORD_UART_BAUD_RATE,
        .data_bits  = UART_DATA_8_BITS,
        .parity     = UART_PARITY_DISABLE,
        .stop_bits  = UART_STOP_BITS_1,
        .flow_ctrl  = UART_HW_FLOWCTRL_DISABLE,
        .source_clk = UART_SCLK_DEFAULT,
    };
    ESP_ERROR_CHECK(uart_param_config(UART_PORT, &cfg));
    ESP_ERROR_CHECK(uart_set_pin(UART_PORT,
        CONFIG_COORD_UART_TXD_PIN, CONFIG_COORD_UART_RXD_PIN,
        UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE));
    esp_err_t e = uart_driver_install(UART_PORT, RX_DRIVER_BUF, TX_DRIVER_BUF,
                                      0, NULL, 0);
    if (e != ESP_OK && e != ESP_ERR_INVALID_STATE) ESP_ERROR_CHECK(e);

    s_rx_q = xQueueCreate(RX_QUEUE_DEPTH, sizeof(rx_item_t));
    s_tx_q = xQueueCreate(TX_QUEUE_DEPTH, sizeof(tx_item_t));
    configASSERT(s_rx_q != NULL && s_tx_q != NULL);

    xTaskCreate(tx_task, "coord_tx", 3072, NULL, 9, NULL);
    xTaskCreate(rx_task, "coord_rx", 4096, NULL, 10, NULL);
    ESP_LOGI(TAG, "link up on UART%d", CONFIG_COORD_UART_PORT);
}
