/*
 * Smart Kosher H2/C6 Zigbee coordinator — entry point only.
 *
 * The firmware is split so that the parts worth testing can be tested:
 *
 *   protocol.c  wire envelope (CRC + line assembly)      pure, host-tested
 *   txn.c       in-flight request table                  pure, host-tested
 *   link.c      UART tasks + bounded queues              ESP, no Zigbee
 *   zb.c        radio stack, commands, events            ESP + Zigbee
 *   main.c      this file: NVS, link, boot beacon, task
 *
 * The two rules the previous single-file version broke, and that the split
 * enforces: nothing outside the Zigbee scheduler context calls the stack, and
 * nothing but the TX task writes to the UART.
 *
 * H2 remains a stateless execution arm — the S3 owns the device registry and
 * supplies addressing per command. The only state kept here is the in-flight
 * request table and the network-up flag.
 */

#include <stdlib.h>

#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "nvs_flash.h"
#include "sdkconfig.h"

#include "cJSON.h"

#include "link.h"
#include "zb.h"

#define TAG        "H2_COORD"
#define ZB_STORAGE "zb_storage"

static void announce_boot(void)
{
    cJSON *root = cJSON_CreateObject();
    cJSON_AddNumberToObject(root, "version", 1);
    cJSON_AddStringToObject(root, "type", "event");
    cJSON_AddStringToObject(root, "op", "boot");
    cJSON *p = cJSON_AddObjectToObject(root, "payload");
    cJSON_AddStringToObject(p, "firmware",         CONFIG_COORD_FW_NAME);
    cJSON_AddStringToObject(p, "firmware_version", CONFIG_COORD_FW_VERSION);
    cJSON_AddStringToObject(p, "target",           CONFIG_IDF_TARGET);
    cJSON_AddNumberToObject(p, "uart_tx_pin", CONFIG_COORD_UART_TXD_PIN);
    cJSON_AddNumberToObject(p, "uart_rx_pin", CONFIG_COORD_UART_RXD_PIN);

    /* Advertised at boot as well as in ping, so the panel can adapt without
     * waiting for its first heartbeat. */
    cJSON *caps = cJSON_AddArrayToObject(p, "capabilities");
    cJSON_AddItemToArray(caps, cJSON_CreateString("delivery_ack"));
    cJSON_AddItemToArray(caps, cJSON_CreateString("endpoint_discovery"));
    cJSON_AddItemToArray(caps, cJSON_CreateString("cluster_discovery"));
    cJSON_AddItemToArray(caps, cJSON_CreateString("device_left"));
    cJSON_AddItemToArray(caps, cJSON_CreateString("health_counters"));

    char *body = cJSON_PrintUnformatted(root);
    if (body != NULL) {
        /* Repeated because the S3 may still be booting and there is no
         * handshake yet; the queue absorbs them without blocking anyone. */
        for (int i = 0; i < CONFIG_COORD_BOOT_BEACON_COUNT; i++) {
            link_send_body(body);
            vTaskDelay(pdMS_TO_TICKS(250));
        }
        free(body);
    }
    cJSON_Delete(root);
}

void app_main(void)
{
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES ||
        ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ret = nvs_flash_init();
    }
    ESP_ERROR_CHECK(ret);
    ESP_ERROR_CHECK(nvs_flash_init_partition(ZB_STORAGE));

    link_start();
    ESP_LOGI(TAG, "%s %s on %s", CONFIG_COORD_FW_NAME,
             CONFIG_COORD_FW_VERSION, CONFIG_IDF_TARGET);

    xTaskCreate(zb_task, "zb_main", 8192, NULL, 5, NULL);
    announce_boot();
}
