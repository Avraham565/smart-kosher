/*
 * In-flight request table.
 *
 * Replaces the single global slots (s_pending_rid/short, s_bind_pending_*)
 * that made two concurrent requests overwrite each other: pairing two devices
 * inside one permit_join window was enough for one of them to silently never
 * get reporting.
 *
 * Two properties matter and both are why this is a real table, not a struct:
 *
 *  - **Handles carry a generation.** A slot is identified by index+generation,
 *    so a stack callback that arrives after its request expired cannot write
 *    into whatever request has since reused that index. Late callbacks are a
 *    certainty here (radio timeouts), not an edge case.
 *  - **Every slot has a deadline.** A request that is never answered used to
 *    leave its rid set forever, so the *next* device's response was reported
 *    under the wrong request id. Expiry closes the request instead.
 *
 * Pure C: no ESP-IDF, no FreeRTOS. The owner supplies the clock, so the host
 * tests drive time directly.
 */

#ifndef H2_TXN_H
#define H2_TXN_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/*
 * Sized from the network, not from a guess. The hub sends ordinary commands
 * one at a time and waits, so that path needs a single slot -- but
 * enable_reporting is fire-and-forget, and the hub's retry sweep fires every
 * device that is due in one go. Devices that joined together back off in step,
 * so the worst case is "every child retrying at once": max_children (10) plus
 * the command in flight, plus headroom.
 */
#define TXN_MAX     16
#define TXN_RID_MAX 48

/* 0 is never a valid handle, so it doubles as "no transaction". */
typedef uint32_t txn_handle_t;
#define TXN_NONE 0u

typedef enum {
    TXN_KIND_NONE = 0,
    TXN_KIND_ON_OFF,
    TXN_KIND_READ_ATTR,
    TXN_KIND_BIND,
    TXN_KIND_CONFIG_REPORT,
    TXN_KIND_READ_REPORT_CFG,
    TXN_KIND_REMOVE,
} txn_kind_t;

typedef struct {
    bool       in_use;
    uint32_t   generation;
    txn_kind_t kind;
    char       rid[TXN_RID_MAX];
    bool       has_rid;
    uint16_t   short_addr;
    uint8_t    endpoint;
    /* Which cluster the request is about. Set by the caller after alloc, and
     * carried through to the reporting verdict so the hub knows what the
     * verdict is about. Only OnOff is configurable now that measurement is
     * gone, so it is always 0x0006 in practice -- kept because the field is
     * what makes a `reporting_failed` event unambiguous, and because a request
     * for any other cluster must fail loudly rather than be assumed to be
     * OnOff. */
    uint16_t   cluster;
    uint8_t    tsn;          /* filled in once the stack reports it */
    bool       has_tsn;
    int64_t    deadline_ms;
} txn_t;

typedef struct {
    txn_t    slots[TXN_MAX];
    uint32_t next_generation;
    uint32_t peak_in_use;
    uint32_t full_rejections;
} txn_table_t;

void txn_table_init(txn_table_t *table);

/*
 * Claim a slot. ``rid`` may be NULL for a request nobody is waiting on.
 * Returns TXN_NONE when the table is full -- the caller should answer "busy"
 * immediately, which is honest backpressure rather than a silent overwrite.
 */
txn_handle_t txn_alloc(txn_table_t *table, txn_kind_t kind, const char *rid,
                       uint16_t short_addr, uint8_t endpoint,
                       int64_t now_ms, uint32_t timeout_ms);

/* Resolve a handle, or NULL if it expired or was already released. */
txn_t *txn_get(txn_table_t *table, txn_handle_t handle);

void txn_release(txn_table_t *table, txn_handle_t handle);

/* Find the open transaction a device response belongs to. Matching is by the
 * responder's own identity, never by "the last thing we sent": TSN first when
 * the stack gave us one, otherwise the oldest open request of that kind to
 * that address, preferring one to the same endpoint.
 *
 * The endpoint only narrows the fall-back and never outranks TSN. Making the
 * match strict is the dangerous direction: a device answering from an
 * endpoint we did not expect would lose its match and get an expiry instead
 * of a reply, which is worse than the mismatch this exists to prevent. So an
 * endpoint that selects nothing falls back to the old behaviour rather than
 * to TXN_NONE. */
txn_handle_t txn_match(txn_table_t *table, txn_kind_t kind,
                       uint16_t short_addr, uint8_t tsn, bool tsn_valid,
                       uint8_t endpoint, bool endpoint_valid);

/*
 * Release every slot past its deadline, reporting each to ``on_expired``
 * before it is cleared. Returns how many expired.
 */
typedef void (*txn_expired_cb_t)(const txn_t *txn, void *ctx);
uint32_t txn_expire(txn_table_t *table, int64_t now_ms,
                    txn_expired_cb_t on_expired, void *ctx);

uint32_t txn_in_use(const txn_table_t *table);

#endif /* H2_TXN_H */
