/*
 * Host tests for the coordinator's hardware-independent layers.
 *
 * The firmware had no tests at all: every check was a flash-and-squint on a
 * board we cannot always reach. The envelope and the transaction table have no
 * ESP-IDF, FreeRTOS or cJSON dependency, so they build with plain gcc and the
 * bugs that actually bit us (line overrun, dangling request ids, one request
 * clobbering another) are reproducible here in milliseconds.
 *
 * Build and run:  cd host_test && ./run.sh
 */

#include <stdio.h>
#include <string.h>

#include "protocol.h"
#include "txn.h"

static int failures = 0;
static int checks = 0;

#define CHECK(cond, ...)                                        \
    do {                                                        \
        checks++;                                               \
        if (!(cond)) {                                          \
            failures++;                                         \
            printf("FAIL %s:%d: ", __func__, __LINE__);         \
            printf(__VA_ARGS__);                                \
            printf("\n");                                       \
        }                                                       \
    } while (0)

/* ── protocol: CRC ──────────────────────────────────────────────── */

static void test_crc_matches_the_python_side(void)
{
    /* Generated with binascii.crc32 on the other end of this wire. If these
     * ever disagree, every frame in both directions fails its checksum. */
    struct { const char *body; uint32_t crc; } vectors[] = {
        { "",           0x00000000u },
        { "a",          0xe8b7be43u },
        { "123456789",  0xcbf43926u },
        { "{\"version\":1,\"type\":\"command\",\"op\":\"ping\"}", 0x62a3070fu },
    };
    for (size_t i = 0; i < sizeof(vectors) / sizeof(vectors[0]); i++) {
        uint32_t got = proto_crc32(vectors[i].body, strlen(vectors[i].body));
        CHECK(got == vectors[i].crc, "crc32(%s) = %08x want %08x",
              vectors[i].body, got, vectors[i].crc);
    }
}

/* ── protocol: frame validation ─────────────────────────────────── */

static void build_frame(char *out, size_t out_len, const char *body)
{
    snprintf(out, out_len, "%08x %s", proto_crc32(body, strlen(body)), body);
}

static void test_valid_frame_yields_its_body(void)
{
    char line[PROTO_MAX_LINE];
    const char *body = NULL;
    build_frame(line, sizeof(line), "{\"op\":\"ping\"}");

    CHECK(proto_frame_body(line, &body) == PROTO_FRAME_OK, "should accept");
    CHECK(body && strcmp(body, "{\"op\":\"ping\"}") == 0, "body mismatch");
}

static void test_corrupt_body_is_bad_crc_not_bad_prefix(void)
{
    char line[PROTO_MAX_LINE];
    const char *body = NULL;
    build_frame(line, sizeof(line), "{\"op\":\"ping\"}");
    line[12] ^= 0x01;   /* flip a bit inside the body */

    CHECK(proto_frame_body(line, &body) == PROTO_FRAME_BAD_CRC,
          "a mangled body must be reported as bad_crc");
}

static void test_malformed_prefixes_are_distinguished(void)
{
    const char *bad[] = {
        "nospace",
        "short {}",             /* prefix not 8 chars */
        "toolongprefix {}",
        "ABCDEF12 {}",          /* uppercase: the sender emits lowercase */
        "12345g78 {}",          /* non-hex */
    };
    for (size_t i = 0; i < sizeof(bad) / sizeof(bad[0]); i++) {
        char line[PROTO_MAX_LINE];
        const char *body = NULL;
        snprintf(line, sizeof(line), "%s", bad[i]);
        CHECK(proto_frame_body(line, &body) == PROTO_FRAME_BAD_PREFIX,
              "%s should be BAD_PREFIX", bad[i]);
    }
}

/* ── protocol: line assembler ───────────────────────────────────── */

static bool feed_string(proto_lines_t *lines, const char *s, uint32_t *dropped)
{
    bool ready = false;
    for (const char *p = s; *p; p++) {
        ready = proto_lines_feed(lines, *p, dropped);
    }
    return ready;
}

static void test_assembler_splits_lines_and_strips_cr(void)
{
    proto_lines_t lines;
    proto_lines_init(&lines);

    CHECK(feed_string(&lines, "hello\r\n", NULL), "line should complete");
    CHECK(strcmp(lines.buf, "hello") == 0, "got %s", lines.buf);

    CHECK(feed_string(&lines, "second\n", NULL), "second line");
    CHECK(strcmp(lines.buf, "second") == 0, "got %s", lines.buf);
}

static void test_blank_lines_are_not_frames(void)
{
    proto_lines_t lines;
    proto_lines_init(&lines);
    CHECK(!feed_string(&lines, "\n", NULL), "empty line is not a frame");
    CHECK(!feed_string(&lines, "\r\n", NULL), "bare CRLF is not a frame");
}

static void test_overlong_line_is_dropped_whole(void)
{
    /* The original reader reset its length on overflow and kept appending, so
     * the tail of one overlong line was parsed as a second, bogus frame. */
    proto_lines_t lines;
    proto_lines_init(&lines);
    uint32_t dropped = 0;

    for (int i = 0; i < PROTO_MAX_LINE + 100; i++) {
        CHECK(!proto_lines_feed(&lines, 'x', &dropped), "no frame mid-overrun");
    }
    CHECK(!proto_lines_feed(&lines, '\n', &dropped), "overrun yields no frame");
    CHECK(dropped == 1, "dropped = %u want 1", dropped);

    /* And the next line must be clean, not polluted by the discarded tail. */
    CHECK(feed_string(&lines, "after\n", &dropped), "next line recovers");
    CHECK(strcmp(lines.buf, "after") == 0, "got %s", lines.buf);
    CHECK(dropped == 1, "no extra drops");
}

static void test_a_ping_ack_fits_in_one_line(void)
{
    /* The largest frame this firmware emits. It grew past 512 bytes the moment
     * capabilities and health counters were added, and a truncated body still
     * carries a valid CRC -- so the hub would reject an apparently intact
     * frame and conclude the coordinator never answers a ping. Pinned here so
     * adding a counter cannot quietly reintroduce that. */
    const char *worst_case_ping =
        "{\"version\":1,\"type\":\"ack\",\"op\":\"ping\",\"status\":\"pong\","
        "\"request_id\":\"ping-4294967295\",\"payload\":{"
        "\"firmware\":\"smart_kosher_h2_coordinator\","
        "\"firmware_version\":\"0.8.0\",\"target\":\"esp32h2\","
        "\"network_up\":true,\"capabilities\":[\"delivery_ack\","
        "\"endpoint_discovery\",\"device_left\",\"health_counters\"],"
        "\"health\":{\"uptime_s\":4294967295,\"rx_frames\":4294967295,"
        "\"crc_errors\":4294967295,\"prefix_errors\":4294967295,"
        "\"rx_line_drops\":4294967295,\"rx_queue_drops\":4294967295,"
        "\"tx_queue_drops\":4294967295,\"tx_oversize\":4294967295,"
        "\"tx_peak\":4294967295,\"txn_timeouts\":4294967295,"
        "\"txn_full\":4294967295,\"txn_peak\":4294967295}}}";

    size_t framed = strlen(worst_case_ping) + 9;   /* crc prefix + space */
    CHECK(framed < PROTO_MAX_LINE,
          "worst-case ping frame is %zu bytes, limit %d",
          framed, PROTO_MAX_LINE);
}

/* ── txn table ──────────────────────────────────────────────────── */

static void test_two_requests_do_not_clobber_each_other(void)
{
    /* The bug this table exists to kill: two devices pairing inside one
     * permit_join window shared one global slot, so one silently lost its
     * reporting configuration. */
    txn_table_t table;
    txn_table_init(&table);

    txn_handle_t a = txn_alloc(&table, TXN_KIND_BIND, "rid-a", 0x1111, 1, 0, 5000);
    txn_handle_t b = txn_alloc(&table, TXN_KIND_BIND, "rid-b", 0x2222, 1, 0, 5000);
    CHECK(a != TXN_NONE && b != TXN_NONE && a != b, "distinct handles");

    CHECK(strcmp(txn_get(&table, a)->rid, "rid-a") == 0, "a kept its rid");
    CHECK(strcmp(txn_get(&table, b)->rid, "rid-b") == 0, "b kept its rid");
    CHECK(txn_get(&table, a)->short_addr == 0x1111, "a kept its address");
    CHECK(txn_get(&table, b)->short_addr == 0x2222, "b kept its address");
}

static void test_late_callback_cannot_hit_a_reused_slot(void)
{
    txn_table_t table;
    txn_table_init(&table);

    txn_handle_t old = txn_alloc(&table, TXN_KIND_ON_OFF, "old", 0x1111, 1, 0, 1000);
    txn_release(&table, old);
    txn_handle_t fresh = txn_alloc(&table, TXN_KIND_ON_OFF, "new", 0x2222, 1, 0, 1000);

    CHECK(txn_get(&table, old) == NULL, "stale handle must not resolve");
    CHECK(txn_get(&table, fresh) != NULL, "fresh handle resolves");
    CHECK(strcmp(txn_get(&table, fresh)->rid, "new") == 0, "not corrupted");
}

static void test_every_slot_is_reachable_by_its_handle(void)
{
    /* Allocating all TXN_MAX slots is not the same as being able to find them
     * again. The handle packed the index into a nibble, so raising the table
     * from 8 to 16 made the last slot's index+1 overflow the field: slot 15
     * came back NULL and the sixteenth in-flight request could never be
     * confirmed. Allocation succeeded throughout, which is exactly why the
     * old test missed it.
     */
    txn_table_t table;
    txn_table_init(&table);
    txn_handle_t handles[TXN_MAX];

    for (int i = 0; i < TXN_MAX; i++) {
        handles[i] = txn_alloc(&table, TXN_KIND_ON_OFF, "r",
                               (uint16_t)(0x1000 + i), 1, 0, 5000);
        CHECK(handles[i] != TXN_NONE, "slot %d did not allocate", i);
    }
    for (int i = 0; i < TXN_MAX; i++) {
        txn_t *slot = txn_get(&table, handles[i]);
        CHECK(slot != NULL, "slot %d unreachable (handle 0x%x)", i, handles[i]);
        if (slot != NULL) {
            CHECK(slot->short_addr == (uint16_t)(0x1000 + i),
                  "slot %d resolved to the wrong request", i);
        }
    }
    /* And each must still be distinguishable after a release/reuse cycle. */
    txn_release(&table, handles[TXN_MAX - 1]);
    txn_handle_t reused = txn_alloc(&table, TXN_KIND_ON_OFF, "again",
                                    0x9999, 1, 0, 5000);
    CHECK(txn_get(&table, handles[TXN_MAX - 1]) == NULL, "stale handle lives");
    CHECK(txn_get(&table, reused) != NULL, "reused slot unreachable");
}

static void test_full_table_rejects_instead_of_overwriting(void)
{
    txn_table_t table;
    txn_table_init(&table);
    for (int i = 0; i < TXN_MAX; i++) {
        CHECK(txn_alloc(&table, TXN_KIND_ON_OFF, "r", 0x1000 + i, 1, 0, 1000)
              != TXN_NONE, "slot %d", i);
    }
    CHECK(txn_alloc(&table, TXN_KIND_ON_OFF, "over", 0x9999, 1, 0, 1000)
          == TXN_NONE, "a full table must refuse");
    CHECK(table.full_rejections == 1, "rejection counted");
    CHECK(table.peak_in_use == TXN_MAX, "peak recorded");
}

static void expired_counter(const txn_t *txn, void *ctx)
{
    (void)txn;
    (*(int *)ctx)++;
}

static void test_unanswered_request_expires(void)
{
    /* An unanswered read_attr used to leave its rid set forever, so the next
     * device's response was reported under the wrong request id. */
    txn_table_t table;
    txn_table_init(&table);
    txn_handle_t h = txn_alloc(&table, TXN_KIND_READ_ATTR, "rid", 0x1111, 1,
                               1000, 1500);
    int expired = 0;

    CHECK(txn_expire(&table, 2000, expired_counter, &expired) == 0, "not yet");
    CHECK(txn_get(&table, h) != NULL, "still open");

    CHECK(txn_expire(&table, 2600, expired_counter, &expired) == 1, "expires");
    CHECK(expired == 1, "callback fired once");
    CHECK(txn_get(&table, h) == NULL, "slot released");
}

static void test_match_prefers_tsn_over_guessing(void)
{
    txn_table_t table;
    txn_table_init(&table);

    txn_handle_t first = txn_alloc(&table, TXN_KIND_READ_ATTR, "one", 0x1111, 1, 0, 5000);
    txn_handle_t second = txn_alloc(&table, TXN_KIND_READ_ATTR, "two", 0x1111, 1, 0, 5000);
    txn_get(&table, first)->tsn = 7;
    txn_get(&table, first)->has_tsn = true;
    txn_get(&table, second)->tsn = 9;
    txn_get(&table, second)->has_tsn = true;

    CHECK(txn_match(&table, TXN_KIND_READ_ATTR, 0x1111, 9, true) == second,
          "tsn 9 must resolve to the second request, not the newest slot");
    CHECK(txn_match(&table, TXN_KIND_READ_ATTR, 0x1111, 7, true) == first,
          "tsn 7 resolves to the first");
}

static void test_match_ignores_other_devices(void)
{
    txn_table_t table;
    txn_table_init(&table);
    txn_alloc(&table, TXN_KIND_ON_OFF, "mine", 0x1111, 1, 0, 5000);
    CHECK(txn_match(&table, TXN_KIND_ON_OFF, 0x2222, 0, false) == TXN_NONE,
          "a response from another device must not resolve to our request");
    CHECK(txn_match(&table, TXN_KIND_READ_ATTR, 0x1111, 0, false) == TXN_NONE,
          "a different kind must not resolve either");
}

/* ── runner ─────────────────────────────────────────────────────── */

int main(void)
{
    test_crc_matches_the_python_side();
    test_valid_frame_yields_its_body();
    test_corrupt_body_is_bad_crc_not_bad_prefix();
    test_malformed_prefixes_are_distinguished();
    test_assembler_splits_lines_and_strips_cr();
    test_blank_lines_are_not_frames();
    test_overlong_line_is_dropped_whole();
    test_a_ping_ack_fits_in_one_line();
    test_two_requests_do_not_clobber_each_other();
    test_late_callback_cannot_hit_a_reused_slot();
    test_every_slot_is_reachable_by_its_handle();
    test_full_table_rejects_instead_of_overwriting();
    test_unanswered_request_expires();
    test_match_prefers_tsn_over_guessing();
    test_match_ignores_other_devices();

    printf("%d checks, %d failures\n", checks, failures);
    return failures == 0 ? 0 : 1;
}
