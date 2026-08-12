/*
 * The S3 <-> H2 UART link, and nothing else: this layer knows about bytes,
 * frames and queues, and deliberately knows nothing about Zigbee.
 *
 * That separation is the point. Previously the UART task called straight into
 * the Zigbee stack behind esp_zigbee_lock_acquire(portMAX_DELAY) while the
 * Zigbee task blocked writing to the UART, so inbound bytes piled up in a 1 KiB
 * driver buffer and were dropped without a trace. Here:
 *
 *   - the RX task only parses and enqueues; it never touches the stack,
 *   - the TX task is the only writer, so no mutex and no stack callback ever
 *     blocks on the wire,
 *   - both queues are bounded and every drop is counted, so a saturated link
 *     shows up in ``ping`` instead of being invisible.
 */

#ifndef H2_LINK_H
#define H2_LINK_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

typedef struct {
    uint32_t rx_frames;      /* well-formed frames handed upward */
    uint32_t crc_errors;     /* prefix parsed, checksum disagreed */
    uint32_t prefix_errors;  /* not even a "<8hex> " prefix */
    uint32_t rx_line_drops;  /* overlong lines discarded whole */
    uint32_t rx_queue_drops; /* command queue full: consumer too slow */
    uint32_t rx_oversize_drops; /* command longer than a queue slot */
    uint32_t tx_queue_drops; /* output queue full: wire too slow */
    uint32_t tx_oversize_drops; /* body would not fit a line: never truncated */
    uint32_t tx_peak;        /* high-water mark of the output queue */
} link_stats_t;

/* Install the UART driver and start the RX/TX tasks. */
void link_start(void);

/* Queue one JSON body for transmission; the CRC prefix and newline are added
 * by the TX task. Safe from any task, including Zigbee stack callbacks --
 * it never blocks on the wire. */
void link_send_body(const char *body);

/* Pop one validated JSON body, waiting up to ``wait_ticks`` (0 = poll). The
 * dispatcher blocks here instead of spinning, and the wait doubles as its
 * timer for ageing out in-flight requests. */
bool link_take_command(char *out, size_t out_len, uint32_t wait_ticks);

const link_stats_t *link_stats(void);

#endif /* H2_LINK_H */
