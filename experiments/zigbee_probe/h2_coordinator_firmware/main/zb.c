#include "zb.h"

#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "cJSON.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "sdkconfig.h"

#include "esp_zigbee.h"
#include "ezbee/zha.h"
#include "ezbee/zcl/cluster/electrical_measurement_desc.h"
#include "ezbee/zcl/cluster/metering_desc.h"

#include "link.h"
#include "protocol.h"
#include "txn.h"

#define TAG "H2_ZB"

#define COORD_EP   1
#define REPORT_MAX_INTERVAL_S 3600
#define ZB_ALL_CH  0x07FFF800U
#define ZB_STORAGE "zb_storage"

/* How long the dispatcher waits for work before sweeping expired requests.
 * Small enough to be invisible next to a radio round-trip. */
#define PUMP_INTERVAL_MS 20

/* Bounded, unlike the old firmware's portMAX_DELAY. If the stack is wedged we
 * want to answer "busy" and keep the link alive, not disappear. */
#define STACK_LOCK_WAIT_MS 200

/* A command is expected to be confirmed well inside this; the S3 waits 1500ms
 * for an ack, so the coordinator must answer *before* that -- an expiry that
 * fires after the caller gave up is useless. */
#define CMD_TIMEOUT_MS      1200
/* A read has to survive an extra device round-trip (the response, not just the
 * transmit confirm), but still beat the S3's own patience. */
#define READ_TIMEOUT_MS     1300
/* Bind + configure_reporting is a background chain nobody blocks on. */
#define REPORTING_TIMEOUT_MS 8000

/* APS/AF data confirm: 0 is success by Zigbee convention. The raw value is
 * echoed in the ack payload so an unexpected code is diagnosable from the S3
 * without a debugger. */
#define AF_STATUS_SUCCESS 0

static bool         s_net_up;
static txn_table_t  s_txn;
static uint32_t     s_txn_timeouts;

/* The table is reached from two contexts -- the dispatcher task and the
 * stack's own confirmation callbacks -- so it gets its own mutex rather than
 * relying on an undocumented assumption about which lock the stack holds while
 * calling us. Ordering is always stack lock (if any) then this one, never the
 * reverse, so the two cannot deadlock. */
static SemaphoreHandle_t s_txn_mutex;

#define TXN_LOCK()   xSemaphoreTakeRecursive(s_txn_mutex, portMAX_DELAY)
#define TXN_UNLOCK() xSemaphoreGiveRecursive(s_txn_mutex)

static int64_t now_ms(void);

/* Locked shorthands for the two single-step operations. Sequences that read a
 * slot and then act on it hold TXN_LOCK explicitly instead, so the slot cannot
 * be recycled between the read and the use. */
static txn_handle_t zb_txn_alloc(txn_kind_t kind, const char *rid,
                                 uint16_t short_addr, uint8_t endpoint,
                                 uint32_t timeout_ms)
{
    TXN_LOCK();
    txn_handle_t h = txn_alloc(&s_txn, kind, rid, short_addr, endpoint,
                               now_ms(), timeout_ms);
    TXN_UNLOCK();
    return h;
}

static void zb_txn_release(txn_handle_t handle)
{
    TXN_LOCK();
    txn_release(&s_txn, handle);
    TXN_UNLOCK();
}

/* ── time ───────────────────────────────────────────────────────── */

static int64_t now_ms(void) { return esp_timer_get_time() / 1000; }

/* ── outbound frames ────────────────────────────────────────────── */

static void send_json(cJSON *root)
{
    char *body = cJSON_PrintUnformatted(root);
    if (body == NULL) return;
    link_send_body(body);
    free(body);
}

static void send_event(const char *op, cJSON *payload)
{
    cJSON *root = cJSON_CreateObject();
    cJSON_AddNumberToObject(root, "version", 1);
    cJSON_AddStringToObject(root, "type", "event");
    cJSON_AddStringToObject(root, "op", op);
    if (payload) cJSON_AddItemToObject(root, "payload", payload);
    send_json(root);
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
    send_json(root);
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
    send_json(root);
    cJSON_Delete(root);
}

/* ── measurement clusters ───────────────────────────────────────── */

#define CLUSTER_ON_OFF       0x0006
#define CLUSTER_METERING     0x0702
#define CLUSTER_ELECTRICAL   0x0B04

/* Attributes we ask a capable device to report, with the ZCL type each one
 * carries. The firmware owns this table rather than the panel: these are ZCL
 * facts, and a hub that had to supply attribute types would be encoding the
 * same knowledge one layer further from the radio. */
typedef struct {
    uint16_t cluster;
    uint16_t attr;
    uint8_t  type;
    /* How much the value must move before the device bothers to report.
     * ZCL calls this the reportable change, and it is REQUIRED for analog
     * attributes -- leaving it zero made the stack reject the whole configure
     * locally (`configure_send_failed`), which is exactly why OnOff worked and
     * every measurement did not: a boolean is discrete and needs none. */
    uint32_t change;
    const char *name;
} report_spec_t;

static const report_spec_t REPORT_SPECS[] = {
    { CLUSTER_ON_OFF,     0x0000, EZB_ZCL_ATTR_TYPE_BOOL,   0, "on_off"      },
    /* One raw unit each -- deliberately the most sensitive setting, paired
     * with a 10 s floor between reports (the user's choice: update every 10 s
     * on any movement, rather than every 2 s on a large one). What a unit is
     * worth depends on the device's own divisors, which we do not read yet. */
    { CLUSTER_ELECTRICAL, 0x050B, EZB_ZCL_ATTR_TYPE_INT16,  1, "active_power"},
    { CLUSTER_ELECTRICAL, 0x0505, EZB_ZCL_ATTR_TYPE_UINT16, 1, "rms_voltage" },
    { CLUSTER_ELECTRICAL, 0x0508, EZB_ZCL_ATTR_TYPE_UINT16, 1, "rms_current" },
    { CLUSTER_METERING,   0x0000, EZB_ZCL_ATTR_TYPE_UINT48, 1, "energy"      },
};
#define REPORT_SPEC_COUNT (sizeof(REPORT_SPECS) / sizeof(REPORT_SPECS[0]))
#define MAX_RECORDS_PER_CLUSTER 3

/* A measurement changes constantly, so unlike OnOff it must not be reported on
 * every flicker -- that would flood the mesh and the link for no benefit. */
#define MEASURE_MIN_INTERVAL_S 10
#define MEASURE_MAX_INTERVAL_S 600

static const char *attr_name(uint16_t cluster, uint16_t attr)
{
    for (size_t i = 0; i < REPORT_SPEC_COUNT; i++) {
        if (REPORT_SPECS[i].cluster == cluster && REPORT_SPECS[i].attr == attr) {
            return REPORT_SPECS[i].name;
        }
    }
    return NULL;
}

/* ZCL integers are little-endian buffers of a type-dependent width. Decoded
 * bytewise because the payload is not guaranteed to be aligned. */
static bool zcl_number(uint8_t type, const void *value, double *out)
{
    const uint8_t *p = (const uint8_t *)value;
    int width;
    bool is_signed = false;

    switch (type) {
    case EZB_ZCL_ATTR_TYPE_BOOL:   width = 1; break;
    case EZB_ZCL_ATTR_TYPE_UINT8:  width = 1; break;
    case EZB_ZCL_ATTR_TYPE_UINT16: width = 2; break;
    case EZB_ZCL_ATTR_TYPE_UINT24: width = 3; break;
    case EZB_ZCL_ATTR_TYPE_UINT32: width = 4; break;
    case EZB_ZCL_ATTR_TYPE_UINT48: width = 6; break;
    case EZB_ZCL_ATTR_TYPE_INT8:   width = 1; is_signed = true; break;
    case EZB_ZCL_ATTR_TYPE_INT16:  width = 2; is_signed = true; break;
    case EZB_ZCL_ATTR_TYPE_INT32:  width = 4; is_signed = true; break;
    default: return false;
    }

    uint64_t raw = 0;
    for (int i = width - 1; i >= 0; i--) raw = (raw << 8) | p[i];

    if (is_signed && (p[width - 1] & 0x80)) {
        /* Sign-extend: active power is negative when a meter reads export. */
        *out = (double)((int64_t)raw - ((int64_t)1 << (width * 8)));
    } else {
        *out = (double)raw;
    }
    return true;
}

/* ── address helpers ────────────────────────────────────────────── */

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

static void short_to_str(uint16_t addr, char *buf, size_t len)
{
    snprintf(buf, len, "0x%04x", addr);
}

static bool short_from_json(cJSON *payload, uint16_t *out)
{
    cJSON *a = cJSON_GetObjectItemCaseSensitive(payload, "short_addr");
    if (!cJSON_IsString(a)) return false;
    unsigned long v = strtoul(a->valuestring, NULL, 16);
    if (v == 0 || v >= 0xFFFF) return false;
    *out = (uint16_t)v;
    return true;
}

static uint8_t endpoint_from_json(cJSON *payload)
{
    cJSON *e = cJSON_GetObjectItemCaseSensitive(payload, "endpoint");
    return (cJSON_IsNumber(e) && e->valueint > 0 && e->valueint < 241)
        ? (uint8_t)e->valueint : 1;
}

/* ── transaction completion ─────────────────────────────────────── */

static const char *kind_op(txn_kind_t kind)
{
    switch (kind) {
    case TXN_KIND_ON_OFF:         return "on_off";
    case TXN_KIND_READ_ATTR:      return "read_attr";
    case TXN_KIND_BIND:           return "enable_reporting";
    case TXN_KIND_CONFIG_REPORT:  return "enable_reporting";
    case TXN_KIND_READ_REPORT_CFG: return "read_report_cfg";
    default:                      return "unknown";
    }
}

/* Defined further down with the reporting chain, but the expiry sweep above
 * it also has to conclude a reporting attempt. */
static void report_reporting_outcome(uint16_t short_addr, uint8_t endpoint,
                                     uint16_t cluster, bool ok,
                                     const char *reason, int detail);

/* Finish a request with a delivery verdict. ``status`` is the ACK-ladder rung
 * the S3 maps onto its own contract: "delivered" is the only one it treats as
 * proof the device actually got the command, and therefore the only one that
 * lets a schedule be written to the journal. */
static void finish_txn(txn_handle_t handle, const char *status,
                       uint8_t raw_status)
{
    TXN_LOCK();
    txn_t *txn = txn_get(&s_txn, handle);
    if (txn == NULL) { TXN_UNLOCK(); return; }  /* late callback: ignore */

    char short_s[8];
    short_to_str(txn->short_addr, short_s, sizeof(short_s));
    cJSON *p = cJSON_CreateObject();
    cJSON_AddStringToObject(p, "short_addr", short_s);
    cJSON_AddNumberToObject(p, "endpoint",   txn->endpoint);
    cJSON_AddNumberToObject(p, "aps_status", raw_status);
    if (txn->has_tsn) cJSON_AddNumberToObject(p, "tsn", txn->tsn);

    if (txn->has_rid) {
        send_ack(txn->rid, kind_op(txn->kind), status, p);
    } else {
        cJSON_Delete(p);
    }
    zb_txn_release(handle);
    TXN_UNLOCK();
}

/* The AF data confirm: the device's own radio acknowledged the frame. This is
 * the delivery proof the previous firmware never used -- it acked "ok" the
 * moment the stack accepted the request, so a command that never reached the
 * relay was still recorded by the S3 as executed. */
static void cmd_confirm_cb(ezb_af_user_cnf_t *cnf, void *user_ctx)
{
    txn_handle_t handle = (txn_handle_t)(uintptr_t)user_ctx;

    TXN_LOCK();
    txn_t *txn = txn_get(&s_txn, handle);
    if (txn == NULL) { TXN_UNLOCK(); return; }

    txn->tsn = cnf ? cnf->tsn : 0;
    txn->has_tsn = (cnf != NULL);
    txn_kind_t kind = txn->kind;
    TXN_UNLOCK();

    uint8_t status = cnf ? cnf->status : 0xFF;
    if (status != AF_STATUS_SUCCESS) {
        finish_txn(handle, "failed", status);
        return;
    }
    if (kind == TXN_KIND_READ_ATTR || kind == TXN_KIND_READ_REPORT_CFG) {
        /* Delivered, but the value we were asked for has not arrived yet --
         * the read completes in the ZCL response handler. */
        return;
    }
    finish_txn(handle, "delivered", status);
}

static void expired_txn_cb(const txn_t *txn, void *ctx)
{
    (void)ctx;
    s_txn_timeouts++;
    if (txn->kind == TXN_KIND_CONFIG_REPORT) {
        /* Delivered but the device never answered -- reporting is unproven,
         * so say so rather than leaving the hub to assume it worked. */
        report_reporting_outcome(txn->short_addr, txn->endpoint, txn->cluster,
                                 false, "configure_no_response", -1);
        return;
    }
    if (!txn->has_rid) return;

    char short_s[8];
    short_to_str(txn->short_addr, short_s, sizeof(short_s));
    cJSON *p = cJSON_CreateObject();
    cJSON_AddStringToObject(p, "short_addr", short_s);
    cJSON_AddNumberToObject(p, "endpoint",   txn->endpoint);
    /* Answering is the point: an unanswered request used to leave its id set
     * forever, so the next device's response was reported under it. */
    send_ack(txn->rid, kind_op(txn->kind), "failed", p);
}

/* ── commands ───────────────────────────────────────────────────── */

static void cmd_ping(const char *rid)
{
    const link_stats_t *st = link_stats();
    cJSON *root = cJSON_CreateObject();
    cJSON_AddNumberToObject(root, "version", 1);
    cJSON_AddStringToObject(root, "type", "ack");
    cJSON_AddStringToObject(root, "op", "ping");
    cJSON_AddStringToObject(root, "status", "pong");
    if (rid) cJSON_AddStringToObject(root, "request_id", rid);

    cJSON *p = cJSON_AddObjectToObject(root, "payload");
    cJSON_AddStringToObject(p, "firmware",         CONFIG_COORD_FW_NAME);
    cJSON_AddStringToObject(p, "firmware_version", CONFIG_COORD_FW_VERSION);
    cJSON_AddStringToObject(p, "target",           CONFIG_IDF_TARGET);
    cJSON_AddBoolToObject(p,   "network_up",       s_net_up);

    /* Capability advertisement: the S3 only tightens its journal rule for a
     * coordinator that can actually prove delivery, so an older build keeps
     * working unchanged and no lockstep flash is needed. */
    cJSON *caps = cJSON_AddArrayToObject(p, "capabilities");
    cJSON_AddItemToArray(caps, cJSON_CreateString("delivery_ack"));
    cJSON_AddItemToArray(caps, cJSON_CreateString("endpoint_discovery"));
    cJSON_AddItemToArray(caps, cJSON_CreateString("cluster_discovery"));
    cJSON_AddItemToArray(caps, cJSON_CreateString("device_left"));
    cJSON_AddItemToArray(caps, cJSON_CreateString("health_counters"));

    /* Health counters: without these, diagnosing a field "it just missed one"
     * is source-reading and guesswork. */
    cJSON *h = cJSON_AddObjectToObject(p, "health");
    cJSON_AddNumberToObject(h, "uptime_s",       (double)(now_ms() / 1000));
    cJSON_AddNumberToObject(h, "rx_frames",      st->rx_frames);
    cJSON_AddNumberToObject(h, "crc_errors",     st->crc_errors);
    cJSON_AddNumberToObject(h, "prefix_errors",  st->prefix_errors);
    cJSON_AddNumberToObject(h, "rx_line_drops",  st->rx_line_drops);
    cJSON_AddNumberToObject(h, "rx_queue_drops", st->rx_queue_drops);
    cJSON_AddNumberToObject(h, "rx_oversize",    st->rx_oversize_drops);
    cJSON_AddNumberToObject(h, "tx_queue_drops", st->tx_queue_drops);
    cJSON_AddNumberToObject(h, "tx_oversize",    st->tx_oversize_drops);
    cJSON_AddNumberToObject(h, "tx_peak",        st->tx_peak);
    cJSON_AddNumberToObject(h, "txn_timeouts",   s_txn_timeouts);
    cJSON_AddNumberToObject(h, "txn_full",       s_txn.full_rejections);
    cJSON_AddNumberToObject(h, "txn_peak",       s_txn.peak_in_use);

    send_json(root);
    cJSON_Delete(root);
}

static void cmd_permit_join(const char *rid, cJSON *payload)
{
    if (!s_net_up) { send_error(rid, "no_network", NULL); return; }

    long dur = 180;
    if (payload) {
        cJSON *d = cJSON_GetObjectItemCaseSensitive(payload, "duration");
        if (cJSON_IsNumber(d)) dur = (long)d->valuedouble;
    }
    /* Clamp rather than truncate: (uint8_t)300 silently became 44. 254 is the
     * protocol maximum; 255 means "open forever", which this product must
     * never do by accident. */
    if (dur < 0)   dur = 0;
    if (dur > 254) dur = 254;

    ezb_bdb_open_network((uint8_t)dur);

    cJSON *p = cJSON_CreateObject();
    cJSON_AddNumberToObject(p, "duration", dur);
    send_ack(rid, "permit_join", "ok", p);
}

static void cmd_on_off(const char *rid, cJSON *payload)
{
    uint16_t target;
    if (!payload)                          { send_error(rid, "missing_payload", NULL); return; }
    cJSON *s = cJSON_GetObjectItemCaseSensitive(payload, "state");
    if (!cJSON_IsString(s))                { send_error(rid, "missing_state", NULL); return; }
    if (!short_from_json(payload, &target)) { send_error(rid, "bad_addr", NULL); return; }
    uint8_t ep = endpoint_from_json(payload);
    bool on = strcmp(s->valuestring, "on") == 0;

    txn_handle_t handle = zb_txn_alloc(TXN_KIND_ON_OFF, rid, target, ep, CMD_TIMEOUT_MS);
    if (handle == TXN_NONE) { send_error(rid, "busy", NULL); return; }

    ezb_zcl_on_off_cmd_t cmd = {
        .cmd_ctrl = {
            .dst_addr.addr_mode    = EZB_ADDR_MODE_SHORT,
            .dst_addr.u.short_addr = target,
            .dst_ep                = ep,
            .src_ep                = COORD_EP,
            /* fc.dis_default_rsp stays 0 so the device also answers at ZCL
             * level; the AF confirm below is the primary delivery proof. */
            .cnf_ctx = {
                .cb       = cmd_confirm_cb,
                .user_ctx = (void *)(uintptr_t)handle,
            },
        },
    };

    ezb_err_t rc = on ? ezb_zcl_on_off_on_cmd_req(&cmd)
                      : ezb_zcl_on_off_off_cmd_req(&cmd);
    if (rc != EZB_ERR_NONE) {
        /* The old firmware discarded this and acked "ok" regardless. */
        zb_txn_release(handle);
        send_error(rid, "send_failed", NULL);
        return;
    }
    /* No ack yet on purpose: it is sent from cmd_confirm_cb (delivered/failed)
     * or from the expiry sweep. */
}

static void cmd_read_attr(const char *rid, cJSON *payload)
{
    uint16_t target;
    if (!payload)                           { send_error(rid, "missing_payload", NULL); return; }
    if (!short_from_json(payload, &target)) { send_error(rid, "bad_addr", NULL); return; }
    uint8_t ep = endpoint_from_json(payload);

    txn_handle_t handle = zb_txn_alloc(TXN_KIND_READ_ATTR, rid, target, ep, READ_TIMEOUT_MS);
    if (handle == TXN_NONE) { send_error(rid, "busy", NULL); return; }

    static uint16_t attr_list[] = { 0x0000 /* OnOff */ };

    ezb_zcl_read_attr_cmd_t req = {0};
    req.cmd_ctrl.dst_addr.addr_mode    = EZB_ADDR_MODE_SHORT;
    req.cmd_ctrl.dst_addr.u.short_addr = target;
    req.cmd_ctrl.dst_ep                = ep;
    req.cmd_ctrl.src_ep                = COORD_EP;
    req.cmd_ctrl.fc.direction          = EZB_ZCL_CMD_DIRECTION_TO_SRV;
    req.cmd_ctrl.cluster_id            = EZB_ZCL_CLUSTER_ID_ON_OFF;
    req.cmd_ctrl.cnf_ctx.cb            = cmd_confirm_cb;
    req.cmd_ctrl.cnf_ctx.user_ctx      = (void *)(uintptr_t)handle;
    req.payload.attr_number            = 1;
    req.payload.attr_field             = attr_list;

    if (ezb_zcl_read_attr_cmd_req(&req) != EZB_ERR_NONE) {
        zb_txn_release(handle);
        send_error(rid, "send_failed", NULL);
    }
}

/* ── reporting: bind, then configure, then verify ───────────────── */

/* Emit the outcome of a reporting attempt. Split out because three different
 * places conclude one: the APS confirm (only ever to fail), the device's ZCL
 * response, and the expiry sweep. */
static void report_reporting_outcome(uint16_t short_addr, uint8_t endpoint,
                                     uint16_t cluster, bool ok,
                                     const char *reason, int detail)
{
    char short_s[8];
    short_to_str(short_addr, short_s, sizeof(short_s));
    cJSON *p = cJSON_CreateObject();
    cJSON_AddStringToObject(p, "short_addr", short_s);
    cJSON_AddNumberToObject(p, "endpoint",   endpoint);
    /* WHICH cluster this verdict is about. Without it the hub could not tell
     * an OnOff result from a metering one, and treated any success as proof
     * that wall-switch reporting worked -- or any failure as proof it did
     * not, which is what actually happened: a metering configure that failed
     * flipped a perfectly good OnOff device to reporting=false. */
    cJSON_AddNumberToObject(p, "cluster",    cluster);
    if (ok) {
        cJSON_AddStringToObject(p, "status", "ok");
        send_event("reporting_configured", p);
    } else {
        cJSON_AddStringToObject(p, "reason", reason);
        if (detail >= 0) cJSON_AddNumberToObject(p, "detail", detail);
        send_event("reporting_failed", p);
    }
}

/*
 * The APS confirm for configure_reporting can now only report FAILURE.
 *
 * It used to report success too -- which meant "the request reached the
 * device", not "the device accepted these values", and the two are not the
 * same thing. A device is free to reject an attribute, or to clamp the
 * interval to its own minimum, and it says so in the ZCL response that this
 * firmware previously discarded. Measured consequence: one relay reports every
 * ~3.0 s no matter that we ask for min_interval = 0. So on delivery we keep
 * the transaction open and wait for the device's actual answer.
 */
static void config_report_confirm_cb(ezb_af_user_cnf_t *cnf, void *user_ctx)
{
    uint8_t status = cnf ? cnf->status : 0xFF;
    if (status == AF_STATUS_SUCCESS) {
        return;                     /* wait for on_config_report_rsp */
    }

    txn_handle_t handle = (txn_handle_t)(uintptr_t)user_ctx;
    TXN_LOCK();
    txn_t *txn = txn_get(&s_txn, handle);
    if (txn == NULL) { TXN_UNLOCK(); return; }
    uint16_t short_addr = txn->short_addr;
    uint8_t endpoint = txn->endpoint;
    uint16_t cluster = txn->cluster ? txn->cluster : CLUSTER_ON_OFF;
    txn_release(&s_txn, handle);
    TXN_UNLOCK();

    report_reporting_outcome(short_addr, endpoint, cluster, false,
                             "configure_not_delivered", status);
}

/* The device's own verdict on our configure_reporting. Per ZCL, a wholly
 * successful configure answers with a single SUCCESS record (or none at all);
 * any record with a non-success status means an attribute was refused. */
static void on_config_report_rsp(ezb_zcl_cmd_config_report_rsp_message_t *rsp)
{
    uint16_t src = 0xFFFF;
    if (rsp->in.header) src = rsp->in.header->src_addr.u.short_addr;

    uint8_t refused = EZB_ZCL_STATUS_SUCCESS;
    for (ezb_zcl_config_report_rsp_variable_t *var = rsp->in.variables;
         var != NULL; var = var->next) {
        if (var->status != EZB_ZCL_STATUS_SUCCESS) {
            refused = var->status;
            break;
        }
    }

    TXN_LOCK();
    txn_handle_t handle = txn_match(&s_txn, TXN_KIND_CONFIG_REPORT, src, 0, false);
    txn_t *txn = txn_get(&s_txn, handle);
    uint8_t endpoint = txn ? txn->endpoint : 1;
    /* The response itself carries no cluster, so it comes from the request
     * this answers -- and OnOff is the safe default only because it is what a
     * pre-cluster hub asks for. */
    uint16_t cluster = (txn && txn->cluster) ? txn->cluster : CLUSTER_ON_OFF;
    if (txn != NULL) txn_release(&s_txn, handle);
    TXN_UNLOCK();

    report_reporting_outcome(src, endpoint, cluster,
                             refused == EZB_ZCL_STATUS_SUCCESS,
                             "configure_refused", refused);
}

static void bind_result_cb(const ezb_zdp_bind_req_result_t *result, void *user_ctx)
{
    /* The device this callback belongs to comes from our own handle, not from
     * a global that the next enable_reporting would already have overwritten:
     * pairing two devices in one permit_join window used to lose one of them. */
    txn_handle_t handle = (txn_handle_t)(uintptr_t)user_ctx;

    TXN_LOCK();
    txn_t *txn = txn_get(&s_txn, handle);
    if (txn == NULL) { TXN_UNLOCK(); return; }
    uint16_t target = txn->short_addr;
    uint8_t  ep     = txn->endpoint;
    uint16_t cluster = txn->cluster ? txn->cluster : CLUSTER_ON_OFF;
    txn_release(&s_txn, handle);
    TXN_UNLOCK();

    bool ok = result && result->error == EZB_ERR_NONE &&
              result->rsp && result->rsp->status == EZB_ZDP_STATUS_SUCCESS;
    if (!ok) {
        report_reporting_outcome(target, ep, cluster, false, "bind_failed", -1);
        return;
    }

    txn_handle_t cfg = zb_txn_alloc(TXN_KIND_CONFIG_REPORT, NULL,
                                    target, ep, REPORTING_TIMEOUT_MS);
    if (cfg == TXN_NONE) {
        report_reporting_outcome(target, ep, cluster, false, "busy", -1);
        return;
    }
    TXN_LOCK();
    txn_t *slot = txn_get(&s_txn, cfg);
    if (slot != NULL) slot->cluster = cluster;
    TXN_UNLOCK();

    /* Every attribute this cluster offers, in one command. OnOff is a boolean
     * and must report the instant it flips; a measurement changes constantly
     * and is rate-limited instead, or it would flood the mesh. */
    ezb_zcl_config_report_record_t records[MAX_RECORDS_PER_CLUSTER] = {0};
    uint16_t count = 0;
    for (size_t i = 0; i < REPORT_SPEC_COUNT && count < MAX_RECORDS_PER_CLUSTER; i++) {
        if (REPORT_SPECS[i].cluster != cluster) continue;
        records[count].direction = EZB_ZCL_REPORTING_SEND;
        records[count].attr_id   = REPORT_SPECS[i].attr;
        records[count].client.attr_type = REPORT_SPECS[i].type;
        if (cluster == CLUSTER_ON_OFF) {
            records[count].client.min_interval = 0;
            records[count].client.max_interval = REPORT_MAX_INTERVAL_S;
        } else {
            records[count].client.min_interval = MEASURE_MIN_INTERVAL_S;
            records[count].client.max_interval = MEASURE_MAX_INTERVAL_S;
            /* Written through the union member matching the attribute's own
             * width -- the header is explicit that it "must match attr_type
             * size", and a mismatch is read as a different number entirely. */
            switch (REPORT_SPECS[i].type) {
            case EZB_ZCL_ATTR_TYPE_UINT16:
                records[count].client.reportable_change.u16 =
                    (uint16_t)REPORT_SPECS[i].change;
                break;
            case EZB_ZCL_ATTR_TYPE_INT16:
                records[count].client.reportable_change.s16 =
                    (int16_t)REPORT_SPECS[i].change;
                break;
            case EZB_ZCL_ATTR_TYPE_UINT48:
                records[count].client.reportable_change.u48 =
                    (uint64_t)REPORT_SPECS[i].change;
                break;
            default:
                records[count].client.reportable_change.u32 =
                    REPORT_SPECS[i].change;
                break;
            }
        }
        count++;
    }
    if (count == 0) {
        zb_txn_release(cfg);
        report_reporting_outcome(target, ep, cluster, false, "unsupported_cluster", -1);
        return;
    }

    ezb_zcl_config_report_cmd_t req = {
        .cmd_ctrl = {
            .dst_addr.addr_mode    = EZB_ADDR_MODE_SHORT,
            .dst_addr.u.short_addr = target,
            .dst_ep                = ep,
            .src_ep                = COORD_EP,
            .cluster_id            = cluster,
            .cnf_ctx = {
                .cb       = config_report_confirm_cb,
                .user_ctx = (void *)(uintptr_t)cfg,
            },
        },
        .payload = { .record_number = count, .record_field = records },
    };
    if (ezb_zcl_config_report_cmd_req(&req) != EZB_ERR_NONE) {
        zb_txn_release(cfg);
        report_reporting_outcome(target, ep, cluster, false, "configure_send_failed", -1);
    }
    /* Success is reported only once the configure is actually confirmed. */
}

static void cmd_enable_reporting(const char *rid, cJSON *payload)
{
    uint16_t target;
    if (!payload)                           { send_error(rid, "missing_payload", NULL); return; }
    if (!short_from_json(payload, &target)) { send_error(rid, "bad_addr", NULL); return; }
    uint8_t ep = endpoint_from_json(payload);

    /* Which cluster to make reportable. Defaults to OnOff so an older hub is
     * unaffected; a hub that discovered metering clusters asks for those too. */
    uint16_t cluster = CLUSTER_ON_OFF;
    cJSON *c = cJSON_GetObjectItemCaseSensitive(payload, "cluster");
    if (cJSON_IsNumber(c)) cluster = (uint16_t)c->valueint;

    ezb_zdo_bind_req_t bind_req = {
        .dst_nwk_addr = target,
        .field = {
            .src_ep        = ep,
            .cluster_id    = cluster,
            .dst_addr_mode = EZB_ADDR_MODE_EXT,
            .dst_ep        = COORD_EP,
        },
        .cb = bind_result_cb,
    };
    if (ezb_address_extended_by_short(target, &bind_req.field.src_addr) != EZB_ERR_NONE) {
        send_error(rid, "unknown_device", NULL);
        return;
    }
    ezb_nwk_get_extended_address(&bind_req.field.dst_addr.extended_addr);

    txn_handle_t handle = zb_txn_alloc(TXN_KIND_BIND, NULL, target, ep, REPORTING_TIMEOUT_MS);
    if (handle == TXN_NONE) { send_error(rid, "busy", NULL); return; }
    TXN_LOCK();
    txn_t *slot = txn_get(&s_txn, handle);
    if (slot != NULL) slot->cluster = cluster;
    TXN_UNLOCK();
    bind_req.user_ctx = (void *)(uintptr_t)handle;

    if (ezb_zdo_bind_req(&bind_req) != EZB_ERR_NONE) {
        zb_txn_release(handle);
        send_error(rid, "bind_failed", NULL);
        return;
    }

    /* The command was accepted; whether reporting ends up working is reported
     * later by reporting_configured / reporting_failed. */
    cJSON *p = cJSON_CreateObject();
    cJSON_AddNumberToObject(p, "endpoint", ep);
    cJSON_AddNumberToObject(p, "cluster", cluster);
    char short_s[8];
    short_to_str(target, short_s, sizeof(short_s));
    cJSON_AddStringToObject(p, "short_addr", short_s);
    send_ack(rid, "enable_reporting", "accepted", p);
}

/*
 * Ask a device what reporting configuration it is ACTUALLY running.
 *
 * Exists because "we asked for min_interval = 0" and "the device reports every
 * 3 seconds" were both true at once, and nothing in the system could say which
 * of the two was lying. Devices routinely clamp the interval to their own
 * minimum; this reads back what they settled on, so the answer is a
 * measurement instead of an inference.
 */
static void cmd_read_report_cfg(const char *rid, cJSON *payload)
{
    uint16_t target;
    if (!payload)                           { send_error(rid, "missing_payload", NULL); return; }
    if (!short_from_json(payload, &target)) { send_error(rid, "bad_addr", NULL); return; }
    uint8_t ep = endpoint_from_json(payload);

    txn_handle_t handle = zb_txn_alloc(TXN_KIND_READ_REPORT_CFG, rid, target, ep,
                                       READ_TIMEOUT_MS);
    if (handle == TXN_NONE) { send_error(rid, "busy", NULL); return; }

    static ezb_zcl_read_report_config_record_t record;
    record.report_direction = EZB_ZCL_REPORTING_SEND;
    record.attr_id = 0x0000;    /* OnOff */

    ezb_zcl_read_report_config_cmd_t req = {0};
    req.cmd_ctrl.dst_addr.addr_mode    = EZB_ADDR_MODE_SHORT;
    req.cmd_ctrl.dst_addr.u.short_addr = target;
    req.cmd_ctrl.dst_ep                = ep;
    req.cmd_ctrl.src_ep                = COORD_EP;
    req.cmd_ctrl.cluster_id            = EZB_ZCL_CLUSTER_ID_ON_OFF;
    req.cmd_ctrl.fc.direction          = EZB_ZCL_CMD_DIRECTION_TO_SRV;
    req.cmd_ctrl.cnf_ctx.cb            = cmd_confirm_cb;
    req.cmd_ctrl.cnf_ctx.user_ctx      = (void *)(uintptr_t)handle;
    req.payload.record_number          = 1;
    req.payload.record_field           = &record;

    if (ezb_zcl_read_report_config_cmd_req(&req) != EZB_ERR_NONE) {
        zb_txn_release(handle);
        send_error(rid, "send_failed", NULL);
    }
}

static void on_read_report_cfg_rsp(ezb_zcl_cmd_read_report_config_rsp_message_t *rsp)
{
    uint16_t src = 0xFFFF;
    if (rsp->in.header) src = rsp->in.header->src_addr.u.short_addr;

    char rid[TXN_RID_MAX];
    bool awaited = false;
    TXN_LOCK();
    txn_handle_t handle = txn_match(&s_txn, TXN_KIND_READ_REPORT_CFG, src, 0, false);
    txn_t *txn = txn_get(&s_txn, handle);
    if (txn != NULL) {
        awaited = txn->has_rid;
        if (awaited) memcpy(rid, txn->rid, sizeof(rid));
        txn_release(&s_txn, handle);
    }
    TXN_UNLOCK();
    if (!awaited) return;

    char short_s[8];
    short_to_str(src, short_s, sizeof(short_s));
    cJSON *p = cJSON_CreateObject();
    cJSON_AddStringToObject(p, "short_addr", short_s);

    for (ezb_zcl_read_report_config_rsp_variable_t *var = rsp->in.variables;
         var != NULL; var = var->next) {
        if (var->attr_id != 0x0000) continue;
        cJSON_AddNumberToObject(p, "zcl_status", var->status);
        if (var->status == EZB_ZCL_STATUS_SUCCESS &&
            var->direction == EZB_ZCL_REPORTING_SEND) {
            cJSON_AddNumberToObject(p, "min_interval", var->client.min_interval);
            cJSON_AddNumberToObject(p, "max_interval", var->client.max_interval);
        }
        break;
    }
    send_ack(rid, "read_report_cfg", "delivered", p);
}

static void cmd_remove_device(const char *rid, cJSON *payload)
{
    if (!payload) { send_error(rid, "missing_payload", NULL); return; }

    cJSON *ia = cJSON_GetObjectItemCaseSensitive(payload, "ieee_addr");
    if (!cJSON_IsString(ia)) { send_error(rid, "missing_ieee", NULL); return; }
    uint8_t ieee[8];
    if (!ieee_from_str(ia->valuestring, ieee)) {
        send_error(rid, "bad_ieee", NULL);
        return;
    }
    uint16_t target;
    if (!short_from_json(payload, &target)) { send_error(rid, "bad_addr", NULL); return; }

    ezb_zdo_nwk_mgmt_leave_req_t leave = {0};
    leave.dst_nwk_addr = target;
    memcpy(leave.field.device_addr.u8, ieee, 8);
    ezb_zdo_nwk_mgmt_leave_req(&leave);

    cJSON *p = cJSON_CreateObject();
    cJSON_AddStringToObject(p, "ieee_addr", ia->valuestring);
    send_ack(rid, "remove_device", "ok", p);
}

/* ── endpoint and cluster discovery ─────────────────────────────── */

/* Defined below; the endpoint callback chains into it. */
static void discover_clusters(uint16_t target, uint8_t endpoint);

static void active_ep_cb(const ezb_zdo_active_ep_req_result_t *result,
                         void *user_ctx)
{
    uint16_t target = (uint16_t)(uintptr_t)user_ctx;
    char short_s[8];
    short_to_str(target, short_s, sizeof(short_s));

    cJSON *p = cJSON_CreateObject();
    cJSON_AddStringToObject(p, "short_addr", short_s);
    cJSON *list = cJSON_AddArrayToObject(p, "endpoints");

    bool ok = result && result->error == EZB_ERR_NONE && result->rsp &&
              result->rsp->status == EZB_ZDP_STATUS_SUCCESS;
    if (ok) {
        for (uint8_t i = 0; i < result->rsp->active_ep_count; i++) {
            cJSON_AddItemToArray(
                list, cJSON_CreateNumber(result->rsp->active_ep_list[i]));
        }
    }
    /* Chain: now ask each endpoint what clusters it carries. Sent after the
     * event above so the hub learns the endpoints even if a descriptor read
     * fails. */
    if (ok) {
        for (uint8_t i = 0; i < result->rsp->active_ep_count; i++) {
            discover_clusters(target, result->rsp->active_ep_list[i]);
        }
    }
    /* Additive to device_joined rather than replacing it: the S3's pairing
     * flow keeps working untouched, and a two-gang switch simply gains a
     * second endpoint here instead of being permanently reported as one. */
    send_event("device_endpoints", p);
}

/*
 * What a given endpoint can actually DO -- its cluster list.
 *
 * Active_EP alone answers "how many endpoints", which is enough for a
 * multi-gang switch but not for "does this device measure power?". That
 * question had no answer at all before: the firmware only ever touches
 * cluster 0x0006 (OnOff) and discards every report from any other cluster, so
 * a metering device would have been indistinguishable from a plain relay.
 * Here the device says what it supports and the hub can stop guessing from
 * the model number.
 */
static void simple_desc_cb(const ezb_zdo_simple_desc_req_result_t *result,
                           void *user_ctx)
{
    uint16_t target = (uint16_t)((uintptr_t)user_ctx >> 8);
    uint8_t endpoint = (uint8_t)((uintptr_t)user_ctx & 0xFF);

    bool ok = result && result->error == EZB_ERR_NONE && result->rsp &&
              result->rsp->status == EZB_ZDP_STATUS_SUCCESS;
    if (!ok) return;

    const ezb_af_simple_desc_t *desc = &result->rsp->desc;
    char short_s[8];
    short_to_str(target, short_s, sizeof(short_s));

    cJSON *p = cJSON_CreateObject();
    cJSON_AddStringToObject(p, "short_addr", short_s);
    cJSON_AddNumberToObject(p, "endpoint",   endpoint);
    cJSON_AddNumberToObject(p, "device_id",  desc->app_device_id);
    cJSON *in = cJSON_AddArrayToObject(p, "in_clusters");
    cJSON *out = cJSON_AddArrayToObject(p, "out_clusters");
    if (desc->app_cluster_list != NULL) {
        for (uint8_t i = 0; i < desc->app_input_cluster_count; i++) {
            cJSON_AddItemToArray(in,
                cJSON_CreateNumber(desc->app_cluster_list[i]));
        }
        for (uint8_t i = 0; i < desc->app_output_cluster_count; i++) {
            cJSON_AddItemToArray(out, cJSON_CreateNumber(
                desc->app_cluster_list[desc->app_input_cluster_count + i]));
        }
    }
    send_event("device_clusters", p);
}

static void discover_clusters(uint16_t target, uint8_t endpoint)
{
    ezb_zdo_simple_desc_req_t req = {
        .dst_nwk_addr = target,
        .field = { .nwk_addr_of_interest = target, .endpoint = endpoint },
        .cb = simple_desc_cb,
        /* Both identifiers fit in the pointer, so the chained request needs no
         * allocation and no table of its own. */
        .user_ctx = (void *)(uintptr_t)(((uint32_t)target << 8) | endpoint),
    };
    ezb_zdo_simple_desc_req(&req);
}

static void discover_endpoints(uint16_t target)
{
    ezb_zdo_active_ep_req_t req = {
        .dst_nwk_addr = target,
        .field = { .nwk_addr_of_interest = target },
        .cb = active_ep_cb,
        .user_ctx = (void *)(uintptr_t)target,
    };
    ezb_zdo_active_ep_req(&req);
}

/* ── command dispatch ───────────────────────────────────────────── */

static void dispatch(const char *body)
{
    cJSON *root = cJSON_Parse(body);
    if (!root) { send_error(NULL, "bad_json", NULL); return; }

    const char *rid = NULL, *op = NULL;
    cJSON *f = cJSON_GetObjectItemCaseSensitive(root, "request_id");
    if (cJSON_IsString(f)) rid = f->valuestring;
    f = cJSON_GetObjectItemCaseSensitive(root, "op");
    if (cJSON_IsString(f)) op = f->valuestring;
    cJSON *pl = cJSON_GetObjectItemCaseSensitive(root, "payload");

    if      (!op)                                send_error(rid, "bad_json", "missing op");
    else if (strcmp(op, "ping")             == 0) cmd_ping(rid);
    else if (strcmp(op, "permit_join")      == 0) cmd_permit_join(rid, pl);
    else if (strcmp(op, "on_off")           == 0) cmd_on_off(rid, pl);
    else if (strcmp(op, "read_attr")        == 0) cmd_read_attr(rid, pl);
    else if (strcmp(op, "enable_reporting") == 0) cmd_enable_reporting(rid, pl);
    else if (strcmp(op, "remove_device")    == 0) cmd_remove_device(rid, pl);
    else if (strcmp(op, "read_report_cfg")  == 0) cmd_read_report_cfg(rid, pl);
    else                                          send_error(rid, "unknown_op", op);

    cJSON_Delete(root);
}

/*
 * The single dispatcher. One task owns every stack call that originates from
 * the link, and it is the ONLY place this firmware takes the Zigbee lock.
 *
 * The 2.x SDK offers no way to run work inside the stack's own context
 * (esp_zb_scheduler_alarm exists only behind CONFIG_ZB_SDK_1xx), so a lock is
 * unavoidable -- but the harm it used to do is not. Previously the UART reader
 * itself blocked on esp_zigbee_lock_acquire(portMAX_DELAY) while the Zigbee
 * task blocked writing to the UART, so inbound bytes piled up and were dropped.
 * Now the reader only enqueues, this task waits with a bounded timeout, and
 * stack callbacks never touch the wire, so a slow radio can no longer cost us
 * a single received byte.
 */
static void zb_dispatch_task(void *arg)
{
    (void)arg;
    char body[PROTO_MAX_LINE];

    for (;;) {
        if (link_take_command(body, sizeof(body),
                              pdMS_TO_TICKS(PUMP_INTERVAL_MS))) {
            if (esp_zigbee_lock_acquire(pdMS_TO_TICKS(STACK_LOCK_WAIT_MS))) {
                dispatch(body);
                esp_zigbee_lock_release();
            } else {
                /* Answer rather than vanish: the hub can retry a "busy". */
                send_error(NULL, "busy", "stack lock timeout");
            }
        }
        /* Expiry only touches our own table and the outbound queue, so it
         * needs the txn mutex (taken inside) and not the stack lock. */
        TXN_LOCK();
        txn_expire(&s_txn, now_ms(), expired_txn_cb, NULL);
        TXN_UNLOCK();
    }
}

/* ── ZCL responses ──────────────────────────────────────────────── */

static void on_read_attr_rsp(ezb_zcl_cmd_read_attr_rsp_message_t *rsp)
{
    uint16_t src = 0xFFFF;
    uint8_t  tsn = 0;
    bool tsn_valid = false;
    if (rsp->in.header) {
        src = rsp->in.header->src_addr.u.short_addr;
        tsn = rsp->in.header->tsn;
        tsn_valid = true;
    }

    for (ezb_zcl_read_attr_rsp_variable_t *var = rsp->in.variables;
         var != NULL; var = var->next) {
        if (var->attr_id != 0x0000 || !var->attr_value) continue;
        bool on = (*(uint8_t *)var->attr_value) != 0;

        /* Resolved from the responder's own identity, not from "the last read
         * we sent" -- which is how a second read used to steal the first
         * one's request id. */
        char rid[TXN_RID_MAX];
        bool awaited = false;

        TXN_LOCK();
        txn_handle_t handle = txn_match(&s_txn, TXN_KIND_READ_ATTR, src,
                                        tsn, tsn_valid);
        txn_t *txn = txn_get(&s_txn, handle);
        if (txn != NULL) {
            awaited = txn->has_rid;
            if (awaited) memcpy(rid, txn->rid, sizeof(rid));
            txn_release(&s_txn, handle);
        }
        TXN_UNLOCK();

        char short_s[8];
        short_to_str(src, short_s, sizeof(short_s));
        cJSON *p = cJSON_CreateObject();
        cJSON_AddBoolToObject(p,   "on_off",     on);
        cJSON_AddStringToObject(p, "short_addr", short_s);

        if (awaited) {
            send_ack(rid, "read_attr", "delivered", p);
        } else {
            /* Unsolicited or already expired: still real state, so publish it
             * as an event rather than dropping it. */
            send_event("attribute_report", p);
        }
        break;
    }
}

static void on_report_attr(ezb_zcl_cmd_report_attr_message_t *rpt)
{
    uint16_t cluster = rpt->info.cluster_id;
    uint16_t src = 0xFFFF;
    uint8_t  ep  = 0;
    if (rpt->in.header) {
        src = rpt->in.header->src_addr.u.short_addr;
        ep  = rpt->in.header->src_ep;
    }
    char short_s[8];
    short_to_str(src, short_s, sizeof(short_s));

    if (cluster == CLUSTER_ON_OFF) {
        for (ezb_zcl_report_attr_variable_t *var = rpt->in.variables;
             var != NULL; var = var->next) {
            if (var->attr_id != 0x0000 || !var->attr_value) continue;
            cJSON *p = cJSON_CreateObject();
            cJSON_AddStringToObject(p, "short_addr", short_s);
            cJSON_AddNumberToObject(p, "endpoint",   ep);
            cJSON_AddBoolToObject(p, "on_off",
                                  (*(uint8_t *)var->attr_value) != 0);
            send_event("attribute_report", p);
            break;
        }
        return;
    }

    if (cluster != CLUSTER_METERING && cluster != CLUSTER_ELECTRICAL) return;

    /* Measurements are passed straight through, undivided and uninterpreted.
     * The raw value plus its cluster is everything the hub needs to make sense
     * of it later; scaling by the device's own divisors is a decision for the
     * layer that decides to display it. Until this existed the firmware
     * discarded every report that was not OnOff, so a metering relay was
     * indistinguishable from a plain one. */
    cJSON *p = cJSON_CreateObject();
    cJSON_AddStringToObject(p, "short_addr", short_s);
    cJSON_AddNumberToObject(p, "endpoint",   ep);
    cJSON_AddNumberToObject(p, "cluster",    cluster);

    bool any = false;
    for (ezb_zcl_report_attr_variable_t *var = rpt->in.variables;
         var != NULL; var = var->next) {
        double value;
        if (!var->attr_value) continue;
        if (!zcl_number(var->attr_type, var->attr_value, &value)) continue;
        const char *name = attr_name(cluster, var->attr_id);
        if (name != NULL) {
            cJSON_AddNumberToObject(p, name, value);
        } else {
            char key[16];
            snprintf(key, sizeof(key), "attr_%u", (unsigned)var->attr_id);
            cJSON_AddNumberToObject(p, key, value);
        }
        any = true;
    }
    if (any) {
        send_event("measurement_report", p);
    } else {
        cJSON_Delete(p);
    }
}

static void zcl_action_handler(ezb_zcl_core_action_callback_id_t cb_id,
                               void *message)
{
    if (cb_id == EZB_ZCL_CORE_READ_ATTR_RSP_CB_ID) {
        on_read_attr_rsp((ezb_zcl_cmd_read_attr_rsp_message_t *)message);
    } else if (cb_id == EZB_ZCL_CORE_REPORT_ATTR_CB_ID) {
        on_report_attr((ezb_zcl_cmd_report_attr_message_t *)message);
    } else if (cb_id == EZB_ZCL_CORE_CONFIG_REPORT_RSP_CB_ID) {
        on_config_report_rsp((ezb_zcl_cmd_config_report_rsp_message_t *)message);
    } else if (cb_id == EZB_ZCL_CORE_READ_REPORT_CONFIG_RSP_CB_ID) {
        on_read_report_cfg_rsp(
            (ezb_zcl_cmd_read_report_config_rsp_message_t *)message);
    } else if (cb_id == EZB_ZCL_CORE_DEFAULT_RSP_CB_ID) {
        ezb_zcl_cmd_default_rsp_message_t *dr = message;
        ESP_LOGD(TAG, "default_rsp cmd=0x%02x status=0x%02x",
                 dr->in.rsp_to_cmd, dr->in.status_code);
    }
}

/* ── stack signals ──────────────────────────────────────────────── */

static void announce_network(const char *note)
{
    s_net_up = true;
    cJSON *p = cJSON_CreateObject();
    cJSON_AddNumberToObject(p, "channel", ezb_nwk_get_current_channel());
    cJSON_AddNumberToObject(p, "pan_id",  ezb_nwk_get_panid());
    if (note) cJSON_AddStringToObject(p, "note", note);
    send_event("network_formed", p);
}

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
                announce_network("restored_from_nvs");
                /* Deliberately NOT opening the network here. The old firmware
                 * called ezb_bdb_open_network(180) on every reboot, so a power
                 * cut left a customer's mesh accepting joins for three minutes
                 * with nobody asking. Joining is panel-initiated only. */
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
            announce_network(NULL);
            ezb_bdb_start_top_level_commissioning(
                EZB_BDB_MODE_NETWORK_STEERING);
        } else {
            ESP_LOGW(TAG, "formation failed (0x%02x)", st);
            send_event("formation_failed", NULL);
        }
        break;
    }

    case EZB_BDB_SIGNAL_STEERING:
        ESP_LOGI(TAG, "steering complete");
        break;

    case EZB_ZDO_SIGNAL_DEVICE_ANNCE: {
        const ezb_zdo_signal_device_annce_params_t *ann =
            ezb_app_signal_get_params(sig);
        char ieee_s[24], short_s[8];
        ieee_to_str(ann->device_addr.u8, ieee_s, sizeof(ieee_s));
        short_to_str(ann->short_addr, short_s, sizeof(short_s));
        ESP_LOGI(TAG, "device joined: %s short=%s", ieee_s, short_s);

        cJSON *p = cJSON_CreateObject();
        cJSON_AddStringToObject(p, "ieee_addr",  ieee_s);
        cJSON_AddStringToObject(p, "short_addr", short_s);
        cJSON_AddNumberToObject(p, "endpoint",   1);
        send_event("device_joined", p);

        discover_endpoints(ann->short_addr);
        break;
    }

    case EZB_ZDO_SIGNAL_LEAVE_INDICATION: {
        /* Previously unhandled, so the panel kept a departed device in its
         * registry forever. */
        const ezb_zdo_signal_leave_indication_params_t *lv =
            ezb_app_signal_get_params(sig);
        char ieee_s[24], short_s[8];
        ieee_to_str(lv->device_addr.u8, ieee_s, sizeof(ieee_s));
        short_to_str(lv->short_addr, short_s, sizeof(short_s));
        cJSON *p = cJSON_CreateObject();
        cJSON_AddStringToObject(p, "ieee_addr",  ieee_s);
        cJSON_AddStringToObject(p, "short_addr", short_s);
        /* LEAVE_TYPE_REJOIN means it is coming straight back, so the hub keeps
         * the device and just marks it unreachable rather than forgetting it. */
        cJSON_AddBoolToObject(p, "rejoin",
                              lv->leave_type == EZB_ZDO_LEAVE_TYPE_REJOIN);
        send_event("device_left", p);
        break;
    }

    case EZB_NWK_SIGNAL_PERMIT_JOIN_STATUS: {
        uint8_t dur = *(uint8_t *)ezb_app_signal_get_params(sig);
        cJSON *p = cJSON_CreateObject();
        cJSON_AddNumberToObject(p, "duration", dur);
        send_event("permit_join_status", p);
        break;
    }

    case EZB_ZDO_SIGNAL_LEAVE:
    case EZB_NWK_SIGNAL_NO_ACTIVE_LINKS_LEFT:
        /* The network is no longer usable. s_net_up used to be write-once, so
         * ping kept claiming network_up long after the mesh was gone and the
         * panel footer lied about it. */
        s_net_up = false;
        send_event("network_down", NULL);
        break;

    default:
        ESP_LOGD(TAG, "signal 0x%02x", type);
        break;
    }
    return true;
}

/* ── task ───────────────────────────────────────────────────────── */

void zb_task(void *arg)
{
    (void)arg;
    txn_table_init(&s_txn);
    s_txn_mutex = xSemaphoreCreateRecursiveMutex();
    configASSERT(s_txn_mutex != NULL);

    esp_zigbee_config_t cfg = {
        .device_config = {
            .device_type         = EZB_NWK_DEVICE_TYPE_COORDINATOR,
            /* Left false deliberately: install-code joining would lock out the
             * switches this pilot already uses. Recorded as a decision, not a
             * default -- revisit before shipping to customers. */
            .install_code_policy = false,
            /* Direct children, not a network cap -- see Kconfig.projbuild.
             * Tunable rather than a literal because the value it replaced was
             * copied from an SDK example and never justified. */
            .zczr_config         = { .max_children = CONFIG_COORD_MAX_CHILDREN },
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

    ezb_af_device_desc_t           dev    = ezb_af_create_device_desc();
    ezb_zha_on_off_switch_config_t sw_cfg = EZB_ZHA_ON_OFF_SWITCH_CONFIG();
    ezb_af_ep_desc_t               ep     =
        ezb_zha_create_on_off_switch(COORD_EP, &sw_cfg);

    /* Declare the measurement clusters on our own endpoint, as CLIENT.
     *
     * The preset above makes this endpoint an OnOff switch and nothing else,
     * and the stack refuses to send a ZCL frame on a cluster its own endpoint
     * does not carry -- which is why configure_reporting for the metering
     * clusters was rejected locally (`configure_send_failed`) while the
     * identical call for OnOff succeeded. Client role because the direction is
     * the device's server reporting to us.
     */
    ezb_zcl_cluster_desc_t elec = ezb_zcl_electrical_measurement_create_cluster_desc(
        NULL, EZB_ZCL_CLUSTER_CLIENT);
    ezb_zcl_cluster_desc_t meter = ezb_zcl_metering_create_cluster_desc(
        NULL, EZB_ZCL_CLUSTER_CLIENT);
    if (elec != NULL) ezb_af_endpoint_add_cluster_desc(ep, elec);
    if (meter != NULL) ezb_af_endpoint_add_cluster_desc(ep, meter);
    ESP_LOGI(TAG, "measurement clusters registered: elec=%d meter=%d",
             elec != NULL, meter != NULL);

    ESP_ERROR_CHECK(ezb_af_device_add_endpoint_desc(dev, ep));
    ESP_ERROR_CHECK(ezb_af_device_desc_register(dev));
    ezb_zcl_core_action_handler_register(zcl_action_handler);

    ESP_ERROR_CHECK(esp_zigbee_start(false));
    /* Below this task's own priority: the stack's mainloop always wins, and
     * the dispatcher only runs when the radio is idle. */
    xTaskCreate(zb_dispatch_task, "zb_disp", 6144, NULL, 4, NULL);
    esp_zigbee_launch_mainloop();
    esp_zigbee_deinit();
    vTaskDelete(NULL);
}
