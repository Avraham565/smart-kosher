#include "txn.h"

#include <string.h>

/*
 * handle = generation<<8 | (index+1). The +1 keeps 0 reserved for "none", and
 * the generation is what makes a late callback harmless.
 *
 * The index field is a byte, not a nibble. It was a nibble while TXN_MAX was
 * 8; raising the table to 16 made the last slot's index+1 exactly 0x10, which
 * overflowed the field, read back as index 0 - 1, and left slot 15 permanently
 * unreachable -- so a confirmation for the sixteenth in-flight request found
 * nothing and the command was never answered. Sized well past TXN_MAX so
 * growing the table again cannot repeat it.
 */
#define HANDLE_INDEX(h) (((h) & 0xFFu) - 1u)
#define HANDLE_GEN(h)   ((h) >> 8)

static txn_handle_t make_handle(uint32_t index, uint32_t generation)
{
    return (generation << 8) | (index + 1u);
}

void txn_table_init(txn_table_t *table)
{
    memset(table, 0, sizeof(*table));
    table->next_generation = 1;
}

uint32_t txn_in_use(const txn_table_t *table)
{
    uint32_t n = 0;
    for (uint32_t i = 0; i < TXN_MAX; i++) {
        if (table->slots[i].in_use) n++;
    }
    return n;
}

txn_handle_t txn_alloc(txn_table_t *table, txn_kind_t kind, const char *rid,
                       uint16_t short_addr, uint8_t endpoint,
                       int64_t now_ms, uint32_t timeout_ms)
{
    for (uint32_t i = 0; i < TXN_MAX; i++) {
        txn_t *slot = &table->slots[i];
        if (slot->in_use) continue;

        memset(slot, 0, sizeof(*slot));
        slot->in_use      = true;
        /* Masked to the width the handle can actually carry. The handle
         * packs the generation above the index byte and txn_get reads it
         * back with >> 8, so a slot storing more than 24 bits could never
         * match its own handle again -- from 0x01000000 on, every txn_get
         * returned NULL while the table went on issuing handles. */
        slot->generation  = (table->next_generation++) & 0xFFFFFFu;
        slot->kind        = kind;
        slot->short_addr  = short_addr;
        slot->endpoint    = endpoint;
        slot->deadline_ms = now_ms + (int64_t)timeout_ms;
        if (rid != NULL && rid[0] != '\0') {
            strncpy(slot->rid, rid, TXN_RID_MAX - 1);
            slot->rid[TXN_RID_MAX - 1] = '\0';
            slot->has_rid = true;
        }

        uint32_t used = txn_in_use(table);
        if (used > table->peak_in_use) table->peak_in_use = used;
        return make_handle(i, slot->generation);
    }
    table->full_rejections++;
    return TXN_NONE;
}

txn_t *txn_get(txn_table_t *table, txn_handle_t handle)
{
    if (handle == TXN_NONE) return NULL;
    uint32_t index = HANDLE_INDEX(handle);
    if (index >= TXN_MAX) return NULL;
    txn_t *slot = &table->slots[index];
    if (!slot->in_use || slot->generation != HANDLE_GEN(handle)) return NULL;
    return slot;
}

void txn_release(txn_table_t *table, txn_handle_t handle)
{
    txn_t *slot = txn_get(table, handle);
    if (slot != NULL) slot->in_use = false;
}

txn_handle_t txn_match(txn_table_t *table, txn_kind_t kind,
                       uint16_t short_addr, uint8_t tsn, bool tsn_valid,
                       uint8_t endpoint, bool endpoint_valid)
{
    txn_handle_t oldest = TXN_NONE;
    int64_t oldest_deadline = 0;
    txn_handle_t oldest_ep = TXN_NONE;
    int64_t oldest_ep_deadline = 0;

    for (uint32_t i = 0; i < TXN_MAX; i++) {
        txn_t *slot = &table->slots[i];
        if (!slot->in_use || slot->kind != kind) continue;
        if (slot->short_addr != short_addr) continue;

        if (tsn_valid && slot->has_tsn) {
            if (slot->tsn == tsn) return make_handle(i, slot->generation);
            continue;   /* a known, different transaction -- not ours */
        }
        if (oldest == TXN_NONE || slot->deadline_ms < oldest_deadline) {
            oldest = make_handle(i, slot->generation);
            oldest_deadline = slot->deadline_ms;
        }
        /* Same fall-back, restricted to the endpoint that answered. A
         * two-gang switch is one short_addr with two open requests, and
         * without this the second gang's answer closed the first gang's
         * transaction. */
        if (endpoint_valid && slot->endpoint == endpoint &&
            (oldest_ep == TXN_NONE || slot->deadline_ms < oldest_ep_deadline)) {
            oldest_ep = make_handle(i, slot->generation);
            oldest_ep_deadline = slot->deadline_ms;
        }
    }
    /* Never TXN_NONE just because the endpoint matched nothing. */
    return oldest_ep != TXN_NONE ? oldest_ep : oldest;
}

uint32_t txn_expire(txn_table_t *table, int64_t now_ms,
                    txn_expired_cb_t on_expired, void *ctx)
{
    uint32_t expired = 0;
    for (uint32_t i = 0; i < TXN_MAX; i++) {
        txn_t *slot = &table->slots[i];
        if (!slot->in_use || slot->deadline_ms > now_ms) continue;
        if (on_expired != NULL) on_expired(slot, ctx);
        slot->in_use = false;
        expired++;
    }
    return expired;
}
