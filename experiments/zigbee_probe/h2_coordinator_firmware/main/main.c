/*
 * Gate-2 coordinator firmware — ESP32-H2
 * esp-zigbee-sdk v2.x  /  ESP-IDF ≥5.2
 *
 * H2 is a pure execution arm — no device state, no table.
 * S3 owns the device registry and supplies all addressing per command.
 * Per-request state: s_pending_rid/short (read_attr), s_bind_pending_short/ep
 * (enable_reporting bind+configure chain).
 *
 * Gate 3 addition: enable_reporting — binds a joined device's OnOff cluster
 * to this coordinator and configures ZCL attribute reporting, so physical
 * switch presses on the device itself push an unsolicited attribute_report
 * event instead of requiring S3 to poll read_attr.
 *
 * NOTE: EZB_ZCL_CORE_REPORT_ATTR_CB_ID and ezb_zcl_report_attr_message_t
 * field names are inferred by pattern-match against EZB_ZCL_CORE_READ_ATTR_RSP_CB_ID
 * (already proven below) and the underlying esp_zb_core_action_callback_id_t
 * enum (docs.espressif.com/projects/esp-zigbee-sdk) — not yet confirmed
 * against the actual vendored header. First build on real hardware is the
 * verification step; fix names here if the compiler disagrees.
 */

#include <inttypes.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "cJSON.h"
#include "driver/uart.h"
#include "esp_crc.h"
#include "esp_err.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "nvs_flash.h"
#include "sdkconfig.h"

#include "esp_zigbee.h"
#include "ezbee/zha.h"

/* ── constants ──────────────────────────────────────────────────── */

#define TAG        "H2_COORD"
#define FW_NAME    "smart_kosher_h2_coordinator"
#define FW_VERSION "0.6.0"
#define COORD_EP   1
#define REPORT_MAX_INTERVAL_S 3600

#define UART_PORT   ((uart_port_t)CONFIG_COORD_UART_PORT)
#define RX_BUF_SIZE 1024
#define MAX_LINE    512

#define ZB_ALL_CH  0x07FFF800U
#define ZB_STORAGE "zb_storage"

/* ── global state — minimal ─────────────────────────────────────── */

static bool              s_net_up        = false;
static char              s_pending_rid[48];
static uint16_t          s_pending_short = 0xFFFF;
static uint16_t          s_bind_pending_short = 0xFFFF;
static uint8_t           s_bind_pending_ep    = 0;
static SemaphoreHandle_t s_uart_mutex;

/* ── IEEE address helpers ───────────────────────────────────────── */

static void ieee_to_str(const uint8_t *ieee, char *buf, size_t len)
{
    snprintf(buf, len, "%02x:%02x:%02x:%02x:%02x:%02x:%02x:%02x",
             ieee[7], ieee[6], ieee[5], ieee[4],
             ieee[3], ieee[2], ieee[1], ieee[0]);
}

static bool ieee_from_str(const char *s, uint8_t *out)
{
    unsigned v[8];
    if (sscanf(s, "%02x:%02x:%02x:%02x:%02x:%02x:%02x:%02x",
               &v[7], &v[6], &v[5], &v[4],
               &v[3], &v[2], &v[1], &v[0]) != 8)
        return false;
    for (int i = 0; i < 8; i++) out[i] = (uint8_t)v[i];
    return true;
}

/* ── CRC-32 ─────────────────────────────────────────────────────── */

static uint32_t crc_of(const char *body)
{
    return esp_crc32_le(0, (const uint8_t *)body, strlen(body));
}

/* ── UART helpers ───────────────────────────────────────────────── */

static void uart_send_json(cJSON *root)
{
    char *body = cJSON_PrintUnformatted(root);
    if (!body) return;
    char prefix[16];
    int n = snprintf(prefix, sizeof(prefix), "%08" PRIx32 " ", crc_of(body));
    xSemaphoreTake(s_uart_mutex, portMAX_DELAY);
    uart_write_bytes(UART_PORT, prefix, n);
    uart_write_bytes(UART_PORT, body, strlen(body));
    uart_write_bytes(UART_PORT, "\n", 1);
    xSemaphoreGive(s_uart_mutex);
    free(body);
}

static void send_event(const char *op, cJSON *payload)
{
    cJSON *root = cJSON_CreateObject();
    cJSON_AddNumberToObject(root, "version", 1);
    cJSON_AddStringToObject(root, "type", "event");
    cJSON_AddStringToObject(root, "op", op);
    if (payload) cJSON_AddItemToObject(root, "payload", payload);
    uart_send_json(root);
    cJSON_Delete(root);
}

static void send_ack(const char *rid, const char *op,
                     const char *status, cJSON *payload)
{
    cJSON *root = cJSON_CreateObject();
    cJSON_AddNumberToObject(root, "version", 1);
    cJSON_AddStringToObject(root, "type", "ack");
    cJSON_AddStringToObject(root, "op", op);
    cJSON_AddStringToObject(root, "status", status);
    if (rid)     cJSON_AddStringToObject(root, "request_id", rid);
    if (payload) cJSON_AddItemToObject(root, "payload", payload);
    uart_send_json(root);
    cJSON_Delete(root);
}

static void send_error(const char *rid, const char *code, const char *msg)
{
    cJSON *root = cJSON_CreateObject();
    cJSON_AddNumberToObject(root, "version", 1);
    cJSON_AddStringToObject(root, "type", "error");
    if (rid) cJSON_AddStringToObject(root, "request_id", rid);
    cJSON *p = cJSON_AddObjectToObject(root, "payload");
    cJSON_AddStringToObject(p, "code",    code);
    cJSON_AddStringToObject(p, "message", msg ? msg : "");
    uart_send_json(root);
    cJSON_Delete(root);
}

/* ── ZCL action handler (Zigbee-task context) ───────────────────── */

static void zcl_action_handler(ezb_zcl_core_action_callback_id_t cb_id,
                                void *message)
{
    if (cb_id == EZB_ZCL_CORE_READ_ATTR_RSP_CB_ID) {
        ezb_zcl_cmd_read_attr_rsp_message_t *rsp = message;
        ezb_zcl_read_attr_rsp_variable_t    *var = rsp->in.variables;
        while (var) {
            if (var->attr_id == 0x0000 /* OnOff */ && var->attr_value) {
                uint8_t raw = *(uint8_t *)var->attr_value;
                char short_s[8];
                snprintf(short_s, sizeof(short_s), "0x%04x", s_pending_short);
                cJSON *p = cJSON_CreateObject();
                cJSON_AddBoolToObject(p,   "on_off",     raw != 0);
                cJSON_AddStringToObject(p, "short_addr", short_s);
                send_ack(s_pending_rid[0] ? s_pending_rid : NULL,
                         "read_attr", "ok", p);
                s_pending_rid[0] = '\0';
                s_pending_short  = 0xFFFF;
                break;
            }
            var = var->next;
        }
    } else if (cb_id == EZB_ZCL_CORE_DEFAULT_RSP_CB_ID) {
        ezb_zcl_cmd_default_rsp_message_t *dr = message;
        ESP_LOGD(TAG, "zcl default_rsp status=0x%02x", dr->in.status_code);
    } else if (cb_id == EZB_ZCL_CORE_REPORT_ATTR_CB_ID) {
        /* Unsolicited attribute report — e.g. physical switch press on the
         * device itself, pushed to us because of enable_reporting's bind +
         * configure_reporting. Struct confirmed against the vendored header
         * (ezbee/zcl/zcl_general_cmd.h) on first build — same shape as the
         * READ_ATTR_RSP handler above (info + in.variables linked list). */
        ezb_zcl_cmd_report_attr_message_t *rpt = message;
        if (rpt->info.cluster_id == EZB_ZCL_CLUSTER_ID_ON_OFF) {
            ezb_zcl_report_attr_variable_t *var = rpt->in.variables;
            while (var) {
                if (var->attr_id == 0x0000 /* OnOff */ && var->attr_value) {
                    uint8_t raw = *(uint8_t *)var->attr_value;
                    uint16_t src_short = 0xFFFF;
                    uint8_t  src_ep    = 0;
                    if (rpt->in.header) {
                        src_short = rpt->in.header->src_addr.u.short_addr;
                        src_ep    = rpt->in.header->src_ep;
                    }
                    char short_s[8];
                    snprintf(short_s, sizeof(short_s), "0x%04x", src_short);
                    cJSON *p = cJSON_CreateObject();
                    cJSON_AddStringToObject(p, "short_addr", short_s);
                    cJSON_AddNumberToObject(p, "endpoint",   src_ep);
                    cJSON_AddBoolToObject(p,   "on_off",     raw != 0);
                    send_event("attribute_report", p);
                    break;
                }
                var = var->next;
            }
        }
    }
}

/* ── App signal handler (Zigbee-task context) ───────────────────── */

static bool app_signal_handler(const ezb_app_signal_t *sig)
{
    ezb_app_signal_type_t type = ezb_app_signal_get_type(sig);

    switch (type) {

    case EZB_ZDO_SIGNAL_SKIP_STARTUP:
        ezb_bdb_start_top_level_commissioning(EZB_BDB_MODE_INITIALIZATION);
        break;

    case EZB_BDB_SIGNAL_DEVICE_FIRST_START:
    case EZB_BDB_SIGNAL_DEVICE_REBOOT: {
        ezb_bdb_comm_status_t st =
            *((ezb_bdb_comm_status_t *)ezb_app_signal_get_params(sig));
        if (st == EZB_BDB_STATUS_SUCCESS) {
            if (ezb_bdb_is_factory_new()) {
                ESP_LOGI(TAG, "first boot — forming network");
                ezb_bdb_start_top_level_commissioning(
                    EZB_BDB_MODE_NETWORK_FORMATION);
            } else {
                s_net_up = true;
                cJSON *p = cJSON_CreateObject();
                cJSON_AddNumberToObject(p, "channel",
                    ezb_nwk_get_current_channel());
                cJSON_AddNumberToObject(p, "pan_id", ezb_nwk_get_panid());
                cJSON_AddStringToObject(p, "note", "restored_from_nvs");
                send_event("network_formed", p);
                ezb_bdb_open_network(180);
            }
        } else {
            ESP_LOGW(TAG, "init failed (0x%02x)", st);
        }
        break;
    }

    case EZB_BDB_SIGNAL_FORMATION: {
        ezb_bdb_comm_status_t st =
            *((ezb_bdb_comm_status_t *)ezb_app_signal_get_params(sig));
        if (st == EZB_BDB_STATUS_SUCCESS) {
            s_net_up = true;
            cJSON *p = cJSON_CreateObject();
            cJSON_AddNumberToObject(p, "channel",
                ezb_nwk_get_current_channel());
            cJSON_AddNumberToObject(p, "pan_id", ezb_nwk_get_panid());
            send_event("network_formed", p);
            ezb_bdb_start_top_level_commissioning(
                EZB_BDB_MODE_NETWORK_STEERING);
        } else {
            ESP_LOGW(TAG, "formation failed (0x%02x)", st);
            send_event("formation_failed", NULL);
        }
        break;
    }

    case EZB_BDB_SIGNAL_STEERING: {
        ezb_bdb_comm_status_t st =
            *((ezb_bdb_comm_status_t *)ezb_app_signal_get_params(sig));
        if (st == EZB_BDB_STATUS_SUCCESS) {
            ESP_LOGI(TAG, "steering done — network open for joins");
        }
        break;
    }

    case EZB_ZDO_SIGNAL_DEVICE_ANNCE: {
        const ezb_zdo_signal_device_annce_params_t *ann =
            ezb_app_signal_get_params(sig);
        char ieee_s[24];
        char short_s[8];
        ieee_to_str(ann->device_addr.u8, ieee_s, sizeof(ieee_s));
        snprintf(short_s, sizeof(short_s), "0x%04x", ann->short_addr);
        ESP_LOGI(TAG, "device joined: %s short=%s", ieee_s, short_s);
        cJSON *p = cJSON_CreateObject();
        cJSON_AddStringToObject(p, "ieee_addr",  ieee_s);
        cJSON_AddStringToObject(p, "short_addr", short_s);
        cJSON_AddNumberToObject(p, "endpoint",   1);
        send_event("device_joined", p);
        break;
    }

    case EZB_NWK_SIGNAL_PERMIT_JOIN_STATUS: {
        uint8_t dur = *(uint8_t *)ezb_app_signal_get_params(sig);
        cJSON *p    = cJSON_CreateObject();
        cJSON_AddNumberToObject(p, "duration", dur);
        send_event("permit_join_status", p);
        break;
    }

    default:
        ESP_LOGD(TAG, "signal 0x%02x", type);
        break;
    }
    return true;
}

/* ── Command handlers (UART-task context) ───────────────────────── */

static void cmd_ping(const char *rid)
{
    cJSON *root = cJSON_CreateObject();
    cJSON_AddNumberToObject(root, "version", 1);
    cJSON_AddStringToObject(root, "type", "ack");
    cJSON_AddStringToObject(root, "op", "ping");
    cJSON_AddStringToObject(root, "status", "pong");
    if (rid) cJSON_AddStringToObject(root, "request_id", rid);
    cJSON *p = cJSON_AddObjectToObject(root, "payload");
    cJSON_AddStringToObject(p, "firmware",         FW_NAME);
    cJSON_AddStringToObject(p, "firmware_version", FW_VERSION);
    cJSON_AddBoolToObject(p,   "network_up",       s_net_up);
    uart_send_json(root);
    cJSON_Delete(root);
}

static void cmd_permit_join(const char *rid, cJSON *payload)
{
    if (!s_net_up) { send_error(rid, "no_network", NULL); return; }
    uint8_t dur = 180;
    if (payload) {
        cJSON *d = cJSON_GetObjectItemCaseSensitive(payload, "duration");
        if (cJSON_IsNumber(d)) dur = (uint8_t)d->valueint;
    }
    esp_zigbee_lock_acquire(portMAX_DELAY);
    ezb_bdb_open_network(dur);
    esp_zigbee_lock_release();
    cJSON *p = cJSON_CreateObject();
    cJSON_AddNumberToObject(p, "duration", dur);
    send_ack(rid, "permit_join", "ok", p);
}

static void cmd_on_off(const char *rid, cJSON *payload)
{
    if (!payload) { send_error(rid, "missing_payload", NULL); return; }

    cJSON *s = cJSON_GetObjectItemCaseSensitive(payload, "state");
    cJSON *a = cJSON_GetObjectItemCaseSensitive(payload, "short_addr");
    if (!cJSON_IsString(s)) { send_error(rid, "missing_state", NULL); return; }
    if (!cJSON_IsString(a)) { send_error(rid, "missing_addr",  NULL); return; }

    bool on = strcmp(s->valuestring, "on") == 0;
    unsigned long v = strtoul(a->valuestring, NULL, 16);
    if (v == 0 || v >= 0xFFFF) { send_error(rid, "bad_addr", NULL); return; }
    uint16_t target = (uint16_t)v;

    uint8_t ep = 1;
    cJSON *e = cJSON_GetObjectItemCaseSensitive(payload, "endpoint");
    if (cJSON_IsNumber(e)) ep = (uint8_t)e->valueint;

    ezb_zcl_on_off_cmd_t cmd = {
        .cmd_ctrl = {
            .dst_addr.addr_mode    = EZB_ADDR_MODE_SHORT,
            .dst_addr.u.short_addr = target,
            .dst_ep                = ep,
            .src_ep                = COORD_EP,
        },
    };
    esp_zigbee_lock_acquire(portMAX_DELAY);
    if (on) ezb_zcl_on_off_on_cmd_req(&cmd);
    else    ezb_zcl_on_off_off_cmd_req(&cmd);
    esp_zigbee_lock_release();

    cJSON *p = cJSON_CreateObject();
    cJSON_AddStringToObject(p, "state",      on ? "on" : "off");
    cJSON_AddStringToObject(p, "short_addr", a->valuestring);
    send_ack(rid, "on_off", "ok", p);
}

static void cmd_read_attr(const char *rid, cJSON *payload)
{
    if (!payload) { send_error(rid, "missing_payload", NULL); return; }

    cJSON *a = cJSON_GetObjectItemCaseSensitive(payload, "short_addr");
    if (!cJSON_IsString(a)) { send_error(rid, "missing_addr", NULL); return; }

    unsigned long v = strtoul(a->valuestring, NULL, 16);
    if (v == 0 || v >= 0xFFFF) { send_error(rid, "bad_addr", NULL); return; }
    uint16_t target = (uint16_t)v;

    uint8_t ep = 1;
    cJSON *e = cJSON_GetObjectItemCaseSensitive(payload, "endpoint");
    if (cJSON_IsNumber(e)) ep = (uint8_t)e->valueint;

    if (rid) {
        strncpy(s_pending_rid, rid, sizeof(s_pending_rid) - 1);
        s_pending_rid[sizeof(s_pending_rid) - 1] = '\0';
    } else {
        s_pending_rid[0] = '\0';
    }
    s_pending_short = target;

    static uint16_t attr_list[] = { 0x0000 /* OnOff */ };

    ezb_zcl_read_attr_cmd_t req = {0};
    req.cmd_ctrl.dst_addr.addr_mode    = EZB_ADDR_MODE_SHORT;
    req.cmd_ctrl.dst_addr.u.short_addr = target;
    req.cmd_ctrl.dst_ep                = ep;
    req.cmd_ctrl.src_ep                = COORD_EP;
    req.cmd_ctrl.fc.direction          = EZB_ZCL_CMD_DIRECTION_TO_SRV;
    req.cmd_ctrl.cluster_id            = EZB_ZCL_CLUSTER_ID_ON_OFF;
    req.payload.attr_number            = 1;
    req.payload.attr_field             = attr_list;

    esp_zigbee_lock_acquire(portMAX_DELAY);
    ezb_zcl_read_attr_cmd_req(&req);
    esp_zigbee_lock_release();
    /* async response arrives via zcl_action_handler */
}

static void bind_result_cb(const ezb_zdp_bind_req_result_t *result, void *user_ctx)
{
    uint16_t target = s_bind_pending_short;
    uint8_t  ep      = s_bind_pending_ep;
    char short_s[8];
    snprintf(short_s, sizeof(short_s), "0x%04x", target);

    bool ok = result && result->error == EZB_ERR_NONE &&
              result->rsp && result->rsp->status == EZB_ZDP_STATUS_SUCCESS;
    if (!ok) {
        cJSON *p = cJSON_CreateObject();
        cJSON_AddStringToObject(p, "short_addr", short_s);
        cJSON_AddNumberToObject(p, "endpoint",   ep);
        cJSON_AddStringToObject(p, "reason",     "bind_failed");
        send_event("reporting_failed", p);
        return;
    }

    /* Device's own OnOff attribute is a boolean — report immediately on any
     * change (min_interval=0) plus a periodic heartbeat (max_interval). */
    ezb_zcl_config_report_record_t record = {
        .direction = EZB_ZCL_REPORTING_SEND,
        .attr_id   = 0x0000, /* OnOff */
        .client    = {
            .attr_type    = EZB_ZCL_ATTR_TYPE_BOOL,
            .min_interval = 0,
            .max_interval = REPORT_MAX_INTERVAL_S,
        },
    };
    ezb_zcl_config_report_cmd_t req = {
        .cmd_ctrl = {
            .dst_addr.addr_mode    = EZB_ADDR_MODE_SHORT,
            .dst_addr.u.short_addr = target,
            .dst_ep                = ep,
            .src_ep                = COORD_EP,
            .cluster_id            = EZB_ZCL_CLUSTER_ID_ON_OFF,
        },
        .payload = {
            .record_number = 1,
            .record_field  = &record,
        },
    };
    esp_zigbee_lock_acquire(portMAX_DELAY);
    ezb_err_t rc = ezb_zcl_config_report_cmd_req(&req);
    esp_zigbee_lock_release();

    cJSON *p = cJSON_CreateObject();
    cJSON_AddStringToObject(p, "short_addr", short_s);
    cJSON_AddNumberToObject(p, "endpoint",   ep);
    cJSON_AddStringToObject(p, "status",     rc == EZB_ERR_NONE ? "ok" : "error");
    send_event("reporting_configured", p);
}

static void cmd_enable_reporting(const char *rid, cJSON *payload)
{
    if (!payload) { send_error(rid, "missing_payload", NULL); return; }

    cJSON *a = cJSON_GetObjectItemCaseSensitive(payload, "short_addr");
    if (!cJSON_IsString(a)) { send_error(rid, "missing_addr", NULL); return; }

    unsigned long v = strtoul(a->valuestring, NULL, 16);
    if (v == 0 || v >= 0xFFFF) { send_error(rid, "bad_addr", NULL); return; }
    uint16_t target = (uint16_t)v;

    uint8_t ep = 1;
    cJSON *e = cJSON_GetObjectItemCaseSensitive(payload, "endpoint");
    if (cJSON_IsNumber(e)) ep = (uint8_t)e->valueint;

    s_bind_pending_short = target;
    s_bind_pending_ep    = ep;

    /* Bind is configured ON the target device: "when your own OnOff (src_ep)
     * changes, tell dst_addr (us)." dst_nwk_addr is who we SEND the ZDO Bind
     * Request to — the target device itself, not us. */
    ezb_zdo_bind_req_t bind_req = {
        .dst_nwk_addr = target,
        .field = {
            .src_ep        = ep,
            .cluster_id    = EZB_ZCL_CLUSTER_ID_ON_OFF,
            .dst_addr_mode = EZB_ADDR_MODE_EXT,
            .dst_ep        = COORD_EP,
        },
        .cb       = bind_result_cb,
        .user_ctx = NULL,
    };
    if (ezb_address_extended_by_short(target, &bind_req.field.src_addr) != EZB_ERR_NONE) {
        send_error(rid, "unknown_device", NULL);
        return;
    }
    ezb_nwk_get_extended_address(&bind_req.field.dst_addr.extended_addr);

    esp_zigbee_lock_acquire(portMAX_DELAY);
    ezb_err_t rc = ezb_zdo_bind_req(&bind_req);
    esp_zigbee_lock_release();
    if (rc != EZB_ERR_NONE) { send_error(rid, "bind_failed", NULL); return; }

    cJSON *p = cJSON_CreateObject();
    cJSON_AddStringToObject(p, "short_addr", a->valuestring);
    cJSON_AddNumberToObject(p, "endpoint",   ep);
    send_ack(rid, "enable_reporting", "ok", p);
    /* reporting_configured / reporting_failed event follows asynchronously
     * from bind_result_cb once the bind response arrives. */
}

static void cmd_remove_device(const char *rid, cJSON *payload)
{
    if (!payload) { send_error(rid, "missing_payload", NULL); return; }

    cJSON *ia = cJSON_GetObjectItemCaseSensitive(payload, "ieee_addr");
    cJSON *sa = cJSON_GetObjectItemCaseSensitive(payload, "short_addr");
    if (!cJSON_IsString(ia)) { send_error(rid, "missing_ieee",  NULL); return; }
    if (!cJSON_IsString(sa)) { send_error(rid, "missing_short", NULL); return; }

    uint8_t ieee[8];
    if (!ieee_from_str(ia->valuestring, ieee)) {
        send_error(rid, "bad_ieee", NULL);
        return;
    }
    unsigned long v = strtoul(sa->valuestring, NULL, 16);
    if (v == 0 || v >= 0xFFFF) { send_error(rid, "bad_addr", NULL); return; }
    uint16_t short_addr = (uint16_t)v;

    ezb_zdo_nwk_mgmt_leave_req_t leave = {0};
    leave.dst_nwk_addr          = short_addr;
    memcpy(leave.field.device_addr.u8, ieee, 8);
    leave.field.remove_children = 0;
    leave.field.rejoin          = 0;
    leave.cb                    = NULL;
    leave.user_ctx              = NULL;
    esp_zigbee_lock_acquire(portMAX_DELAY);
    ezb_zdo_nwk_mgmt_leave_req(&leave);
    esp_zigbee_lock_release();

    cJSON *p = cJSON_CreateObject();
    cJSON_AddStringToObject(p, "ieee_addr",  ia->valuestring);
    cJSON_AddStringToObject(p, "short_addr", sa->valuestring);
    send_ack(rid, "remove_device", "ok", p);
}

/* ── UART frame parser ──────────────────────────────────────────── */

static bool valid_hex8(const char *s)
{
    for (int i = 0; i < 8; i++) {
        char c = s[i];
        if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'))) return false;
    }
    return true;
}

static void handle_frame(char *line)
{
    char *sp = strchr(line, ' ');
    if (!sp || (sp - line) != 8) return;
    *sp = '\0';
    if (!valid_hex8(line)) return;
    const char *body = sp + 1;
    if ((uint32_t)strtoul(line, NULL, 16) != crc_of(body)) {
        send_error(NULL, "bad_crc", NULL);
        return;
    }
    cJSON *root = cJSON_Parse(body);
    if (!root) { send_error(NULL, "bad_json", NULL); return; }

    const char *rid = NULL, *op = NULL;
    cJSON *f = cJSON_GetObjectItemCaseSensitive(root, "request_id");
    if (cJSON_IsString(f)) rid = f->valuestring;
    f = cJSON_GetObjectItemCaseSensitive(root, "op");
    if (cJSON_IsString(f)) op = f->valuestring;
    cJSON *pl = cJSON_GetObjectItemCaseSensitive(root, "payload");

    if      (!op)                                send_error(rid, "bad_json", "missing op");
    else if (strcmp(op, "ping")          == 0)   cmd_ping(rid);
    else if (strcmp(op, "permit_join")   == 0)   cmd_permit_join(rid, pl);
    else if (strcmp(op, "on_off")        == 0)   cmd_on_off(rid, pl);
    else if (strcmp(op, "read_attr")        == 0)   cmd_read_attr(rid, pl);
    else if (strcmp(op, "enable_reporting") == 0)   cmd_enable_reporting(rid, pl);
    else if (strcmp(op, "remove_device")    == 0)   cmd_remove_device(rid, pl);
    else                                         send_error(rid, "unknown_op", op);

    cJSON_Delete(root);
}

/* ── UART reader task ───────────────────────────────────────────── */

static void uart_reader_task(void *arg)
{
    uint8_t buf[128];
    char    line[MAX_LINE];
    size_t  line_len = 0;
    for (;;) {
        int n = uart_read_bytes(UART_PORT, buf, sizeof(buf),
                                pdMS_TO_TICKS(50));
        for (int i = 0; i < n; i++) {
            char ch = (char)buf[i];
            if (ch == '\n') {
                line[line_len] = '\0';
                if (line_len > 0 && line[line_len - 1] == '\r')
                    line[--line_len] = '\0';
                if (line_len > 0) handle_frame(line);
                line_len = 0;
            } else if (line_len < sizeof(line) - 1) {
                line[line_len++] = ch;
            } else {
                line_len = 0; /* line overflow — discard */
            }
        }
    }
}

/* ── Zigbee task ────────────────────────────────────────────────── */

static void zigbee_task(void *arg)
{
    esp_zigbee_config_t cfg = {
        .device_config = {
            .device_type         = EZB_NWK_DEVICE_TYPE_COORDINATOR,
            .install_code_policy = false,
            .zczr_config         = { .max_children = 10 },
        },
        .platform_config = {
            .storage_partition_name = ZB_STORAGE,
            .radio_config           = { .radio_mode = ESP_ZIGBEE_RADIO_MODE_NATIVE },
        },
    };
    ESP_ERROR_CHECK(esp_zigbee_init(&cfg));

    ezb_aps_secur_enable_distributed_security(false);
    ESP_ERROR_CHECK(ezb_bdb_set_primary_channel_set(ZB_ALL_CH));
    ESP_ERROR_CHECK(ezb_bdb_set_secondary_channel_set(ZB_ALL_CH));
    ESP_ERROR_CHECK(ezb_app_signal_add_handler(app_signal_handler));

    ezb_af_device_desc_t            dev    = ezb_af_create_device_desc();
    ezb_zha_on_off_switch_config_t  sw_cfg = EZB_ZHA_ON_OFF_SWITCH_CONFIG();
    ezb_af_ep_desc_t                ep     =
        ezb_zha_create_on_off_switch(COORD_EP, &sw_cfg);
    ESP_ERROR_CHECK(ezb_af_device_add_endpoint_desc(dev, ep));
    ESP_ERROR_CHECK(ezb_af_device_desc_register(dev));
    ezb_zcl_core_action_handler_register(zcl_action_handler);

    ESP_ERROR_CHECK(esp_zigbee_start(false));
    esp_zigbee_launch_mainloop();
    esp_zigbee_deinit();
    vTaskDelete(NULL);
}

/* ── UART init ──────────────────────────────────────────────────── */

static void init_uart(void)
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
    esp_err_t e = uart_driver_install(UART_PORT, RX_BUF_SIZE, 0, 0, NULL, 0);
    if (e != ESP_OK && e != ESP_ERR_INVALID_STATE) ESP_ERROR_CHECK(e);
}

/* ── app_main ───────────────────────────────────────────────────── */

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

    s_uart_mutex = xSemaphoreCreateMutex();
    init_uart();

    {
        cJSON *root = cJSON_CreateObject();
        cJSON_AddNumberToObject(root, "version", 1);
        cJSON_AddStringToObject(root, "type", "event");
        cJSON_AddStringToObject(root, "op", "boot");
        cJSON *p = cJSON_AddObjectToObject(root, "payload");
        cJSON_AddStringToObject(p, "firmware",         FW_NAME);
        cJSON_AddStringToObject(p, "firmware_version", FW_VERSION);
        cJSON_AddNumberToObject(p, "uart_tx_pin", CONFIG_COORD_UART_TXD_PIN);
        cJSON_AddNumberToObject(p, "uart_rx_pin", CONFIG_COORD_UART_RXD_PIN);
        for (int i = 0; i < CONFIG_COORD_BOOT_BEACON_COUNT; i++) {
            uart_send_json(root);
            uart_wait_tx_done(UART_PORT, pdMS_TO_TICKS(100));
            if (i < CONFIG_COORD_BOOT_BEACON_COUNT - 1)
                vTaskDelay(pdMS_TO_TICKS(250));
        }
        cJSON_Delete(root);
    }

    xTaskCreate(uart_reader_task, "coord_uart", 4096, NULL, 10, NULL);
    xTaskCreate(zigbee_task,      "zb_main",    8192, NULL,  5, NULL);
}
