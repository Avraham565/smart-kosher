"""Gate 2 Zigbee proof — run on CrowPanel S3 MicroPython.

Steps:
  1. Wait for H2 boot event.
  2. Wait for network_formed event.
  3. Send permit_join (180 s).
  4. Wait for device_joined event — user must press join/pair on their device now.
  5. Send on_off {"state": "on"}.
  6. Send read_attr — verify on_off == True.
  7. Send on_off {"state": "off"}.
  8. Send read_attr — verify on_off == False.
  9. Report RESULT PASS / FAIL.
"""

import json
import time
from machine import UART

UART_ID          = 1
S3_TX_PIN        = 5
S3_RX_PIN        = 19
BAUD             = 115200
JOIN_TIMEOUT_MS  = 120_000   # 2 min for user to pair device
RESP_TIMEOUT_MS  = 8_000


def crc32(data):
    crc = 0xFFFFFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xEDB88320 if (crc & 1) else crc >> 1
            crc &= 0xFFFFFFFF
    return crc ^ 0xFFFFFFFF


def encode_frame(msg):
    body = json.dumps(msg)
    crc  = crc32(body.encode("utf-8"))
    return ("%08x %s\n" % (crc, body)).encode("utf-8")


def decode_frame(line):
    text = line.decode("utf-8").strip() if isinstance(line, bytes) else line.strip()
    if len(text) < 10 or text[8] != " ":
        raise ValueError("not a framed line")
    expected = int(text[:8], 16)
    body     = text[9:]
    if expected != crc32(body.encode("utf-8")):
        raise ValueError("crc mismatch")
    return json.loads(body)


_ping_seq = 0


def send_cmd(uart, op, payload=None):
    global _ping_seq
    _ping_seq += 1
    msg = {"version": 1, "type": "command", "op": op,
           "request_id": "s3-%s-%d" % (op, _ping_seq)}
    if payload:
        msg["payload"] = payload
    uart.write(encode_frame(msg))
    print("TX  op=%s rid=%s" % (op, msg["request_id"]))
    return msg["request_id"]


def recv_until(uart, buf, match_fn, timeout_ms):
    """Read until match_fn(msg) is True or timeout. Returns msg or None."""
    deadline = time.ticks_add(time.ticks_ms(), timeout_ms)
    while time.ticks_diff(deadline, time.ticks_ms()) > 0:
        chunk = uart.read(256)
        if chunk:
            buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            line = line.strip()
            if not line:
                continue
            try:
                msg = decode_frame(line)
            except Exception:
                try:
                    print("RAW", line.decode("utf-8"))
                except Exception:
                    print("RAW bytes", repr(line))
                continue
            print("RX ", json.dumps(msg))
            if match_fn(msg):
                return msg, buf
        time.sleep_ms(20)
    return None, buf


def main():
    uart = UART(UART_ID, baudrate=BAUD, tx=S3_TX_PIN, rx=S3_RX_PIN, timeout=20)
    print("=== Gate 2 Zigbee probe started ===")
    buf = b""

    # ── 1. confirm H2 is alive (boot event or ping fallback) ─────────────
    print("\n[1] waiting for H2 boot event (5 s) …")
    msg, buf = recv_until(uart, buf,
        lambda m: m.get("op") == "boot", 5_000)
    if msg:
        fw  = msg.get("payload", {}).get("firmware", "?")
        ver = msg.get("payload", {}).get("firmware_version", "?")
        print("    H2 booted: %s %s" % (fw, ver))
    else:
        print("    no boot event — H2 already running, trying ping …")
        rid = send_cmd(uart, "ping")
        pong, buf = recv_until(uart, buf,
            lambda m: m.get("op") == "ping" and m.get("type") == "ack", 8_000)
        if not pong:
            print("RESULT FAIL: H2 not responding (check flash + UART wiring)")
            return
        p = pong.get("payload", {})
        print("    pong: net_up=%s fw=%s %s" % (
            p.get("network_up"), p.get("firmware"), p.get("firmware_version")))

    # ── 2. wait for network_formed ────────────────────────────────────────
    print("\n[2] waiting for network_formed (30 s) …")
    msg, buf = recv_until(uart, buf,
        lambda m: m.get("op") == "network_formed", 30_000)
    if not msg:
        print("RESULT FAIL: Zigbee network did not form")
        return

    ch = msg.get("payload", {}).get("channel", "?")
    print("    network up on channel %s" % ch)

    # ── 3. permit_join ────────────────────────────────────────────────────
    print("\n[3] opening network for join (180 s) …")
    send_cmd(uart, "permit_join", {"duration": 180})
    msg, buf = recv_until(uart, buf,
        lambda m: m.get("op") == "permit_join" and m.get("type") == "ack",
        RESP_TIMEOUT_MS)
    if not msg:
        print("RESULT FAIL: permit_join got no ack")
        return

    # ── 4. wait for device to join ────────────────────────────────────────
    print("\n[4] waiting for device_joined — press pair/join on your device now …")
    msg, buf = recv_until(uart, buf,
        lambda m: m.get("op") == "device_joined", JOIN_TIMEOUT_MS)
    if not msg:
        print("RESULT FAIL: no device joined within timeout")
        return

    short = msg.get("payload", {}).get("short_addr", "?")
    ieee  = msg.get("payload", {}).get("ieee_addr", "?")
    print("    device joined: short=%s ieee=%s" % (short, ieee))

    time.sleep_ms(1000)  # let device settle

    # ── 5. on ─────────────────────────────────────────────────────────────
    print("\n[5] sending on_off ON …")
    send_cmd(uart, "on_off", {"state": "on"})
    msg, buf = recv_until(uart, buf,
        lambda m: m.get("op") == "on_off" and m.get("type") == "ack",
        RESP_TIMEOUT_MS)
    if not msg:
        print("RESULT FAIL: on_off ON got no ack")
        return

    time.sleep_ms(500)

    # ── 6. read attr — verify ON ──────────────────────────────────────────
    print("\n[6] reading on_off attribute (expect True) …")
    send_cmd(uart, "read_attr")
    msg, buf = recv_until(uart, buf,
        lambda m: m.get("op") == "read_attr" and m.get("type") == "ack",
        RESP_TIMEOUT_MS)
    if not msg:
        print("RESULT FAIL: read_attr (ON) timed out — device may not respond")
        return
    actual_on = msg.get("payload", {}).get("on_off")
    if not actual_on:
        print("RESULT FAIL: expected on_off=True, got %s" % actual_on)
        return
    print("    on_off = True ✓")

    time.sleep_ms(500)

    # ── 7. off ────────────────────────────────────────────────────────────
    print("\n[7] sending on_off OFF …")
    send_cmd(uart, "on_off", {"state": "off"})
    msg, buf = recv_until(uart, buf,
        lambda m: m.get("op") == "on_off" and m.get("type") == "ack",
        RESP_TIMEOUT_MS)
    if not msg:
        print("RESULT FAIL: on_off OFF got no ack")
        return

    time.sleep_ms(500)

    # ── 8. read attr — verify OFF ─────────────────────────────────────────
    print("\n[8] reading on_off attribute (expect False) …")
    send_cmd(uart, "read_attr")
    msg, buf = recv_until(uart, buf,
        lambda m: m.get("op") == "read_attr" and m.get("type") == "ack",
        RESP_TIMEOUT_MS)
    if not msg:
        print("RESULT FAIL: read_attr (OFF) timed out")
        return
    actual_off = msg.get("payload", {}).get("on_off")
    if actual_off:
        print("RESULT FAIL: expected on_off=False, got %s" % actual_off)
        return
    print("    on_off = False ✓")

    print("\nRESULT PASS: device joined, on/off verified")


main()
