#include "protocol.h"

#include <string.h>

/* Reflected CRC-32 (poly 0xEDB88320), computed bitwise: 8 bytes of state
 * instead of a 1 KiB table, and this link never moves enough data for the
 * difference to matter. Pinned against the Python side's binascii.crc32 in
 * host_test/test_protocol.c -- if the two ever disagree, every frame fails. */
uint32_t proto_crc32(const void *data, size_t len)
{
    const uint8_t *p = (const uint8_t *)data;
    uint32_t crc = 0xFFFFFFFFU;
    for (size_t i = 0; i < len; i++) {
        crc ^= p[i];
        for (int bit = 0; bit < 8; bit++) {
            uint32_t mask = -(crc & 1U);
            crc = (crc >> 1) ^ (0xEDB88320U & mask);
        }
    }
    return ~crc;
}

static bool is_lower_hex8(const char *s)
{
    for (int i = 0; i < 8; i++) {
        char c = s[i];
        if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'))) return false;
    }
    return true;
}

static uint32_t parse_hex8(const char *s)
{
    uint32_t v = 0;
    for (int i = 0; i < 8; i++) {
        char c = s[i];
        v = (v << 4) | (uint32_t)((c <= '9') ? (c - '0') : (c - 'a' + 10));
    }
    return v;
}

proto_frame_status_t proto_frame_body(char *line, const char **body)
{
    char *sep = strchr(line, ' ');
    if (sep == NULL || (sep - line) != 8 || !is_lower_hex8(line)) {
        return PROTO_FRAME_BAD_PREFIX;
    }
    *sep = '\0';
    const char *payload = sep + 1;
    if (parse_hex8(line) != proto_crc32(payload, strlen(payload))) {
        return PROTO_FRAME_BAD_CRC;
    }
    *body = payload;
    return PROTO_FRAME_OK;
}

void proto_lines_init(proto_lines_t *asm_)
{
    asm_->len = 0;
    asm_->overrun = false;
}

bool proto_lines_feed(proto_lines_t *asm_, char ch, uint32_t *dropped)
{
    if (ch == '\n') {
        bool overran = asm_->overrun;
        size_t len = asm_->len;
        asm_->len = 0;
        asm_->overrun = false;
        if (overran) {
            if (dropped) (*dropped)++;
            return false;
        }
        if (len > 0 && asm_->buf[len - 1] == '\r') len--;
        asm_->buf[len] = '\0';
        return len > 0;
    }
    if (asm_->overrun) return false;   /* discarding to end of line */
    if (asm_->len >= sizeof(asm_->buf) - 1) {
        asm_->overrun = true;
        return false;
    }
    asm_->buf[asm_->len++] = ch;
    return false;
}
