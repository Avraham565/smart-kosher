"""Gate 3 probe — attribute reporting (push-based state, no polling).

Flow:
  1. Confirm H2 alive (boot event or ping fallback).
  2. Wait for network_formed (skip if already up).
  3. Load/restore known device from /devices.json, or open permit_join and
     wait for a fresh pairing.
  4. Send enable_reporting for that device -> wait for reporting_configured.
  5. Prompt: flip the physical switch on the Sonoff -> wait (long timeout)
     for a spontaneous attribute_report event.
  6. RESULT PASS / FAIL.
"""

import json
import time
from machine import UART

UART_ID           = 1
S3_TX_PIN         = 5
S3_RX_PIN         = 19
BAUD              = 115200
JOIN_TIMEOUT_MS   = 120_000
RESP_TIMEOUT_MS   = 8_000
REJOIN_GRACE_MS   = 8_000
PHYSICAL_WAIT_MS  = 300_000
DEVICES_PATH      = "/devices.json"


# ── CRC-32 + frame codec (identical to s3_zigbee_probe.py) ─────────────────

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
    crc = crc32(body.encode("utf-8"))
    return ("%08x %s\n" % (crc, body)).encode("utf-8")


def decode_frame(line):
    text = line.decode("utf-8").strip() if isinstance(line, bytes) else line.strip()
    if len(text) < 10 or text[8] != " ":
        raise ValueError("not a framed line")
    expected = int(text[:8], 16)
    body = text[9:]
    if expected != crc32(body.encode("utf-8")):
        raise ValueError("crc mismatch")
    return json.loads(body)


_seq = 0


def send_cmd(uart, op, payload=None):
    global _seq
    _seq += 1
    msg = {"version": 1, "type": "command", "op": op,
           "request_id": "g3-%s-%d" % (op, _seq)}
    if payload:
        msg["payload"] = payload
    uart.write(encode_frame(msg))
    print("TX  op=%s rid=%s payload=%s" % (op, msg["request_id"], payload))
    return msg["request_id"]


def recv_until(uart, buf, match_fn, timeout_ms, on_msg=None):
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
            if on_msg:
                on_msg(msg)
            if match_fn(msg):
                return msg, buf
        time.sleep_ms(20)
    return None, buf


# ── Device registry ──────────────────────────────────────────────────────

devices = {}


def save_devices():
    try:
        with open(DEVICES_PATH, "w") as f:
            json.dump(devices, f)
    except Exception as e:
        print("    save_devices error:", e)


def load_devices():
    try:
        with open(DEVICES_PATH, "r") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def on_device_joined(msg):
    p = msg.get("payload", {})
    ieee = p.get("ieee_addr")
    short = p.get("short_addr")
    ep = p.get("endpoint", 1)
    if not (ieee and short):
        return
    devices[ieee] = {"short_addr": short, "ep": ep}
    print("    device: %s short=%s ep=%d" % (ieee, short, ep))
    save_devices()


# ── Main probe ────────────────────────────────────────────────────────────

def main():
    global devices

    uart = UART(UART_ID, baudrate=BAUD, tx=S3_TX_PIN, rx=S3_RX_PIN, timeout=20)
    print("=== Gate 3 attribute-reporting probe ===")
    buf = b""

    devices = load_devices()
    if devices:
        print("[1] loaded %d device(s) from %s" % (len(devices), DEVICES_PATH))
    else:
        print("[1] no saved devices — fresh start")

    print("\n[2] waiting for H2 boot event (5 s) ...")
    net_already_up = False
    msg, buf = recv_until(uart, buf, lambda m: m.get("op") == "boot", 5_000)
    if msg:
        p = msg.get("payload", {})
        print("    H2 booted: %s %s" % (p.get("firmware"), p.get("firmware_version")))
    else:
        print("    no boot event — trying ping ...")
        send_cmd(uart, "ping")
        pong, buf = recv_until(uart, buf,
            lambda m: m.get("op") == "ping" and m.get("type") == "ack", 8_000)
        if not pong:
            print("RESULT FAIL: H2 not responding")
            return
        p = pong.get("payload", {})
        net_already_up = bool(p.get("network_up"))
        print("    pong: net_up=%s fw=%s %s" % (
            p.get("network_up"), p.get("firmware"), p.get("firmware_version")))

    if net_already_up:
        print("\n[3] network already up — skipping wait")
    else:
        print("\n[3] waiting for network_formed (30 s) ...")
        msg, buf = recv_until(uart, buf, lambda m: m.get("op") == "network_formed", 30_000)
        if not msg:
            print("RESULT FAIL: Zigbee network did not form")
            return

    print("\n[4] grace period %d ms — waiting for rejoins ..." % REJOIN_GRACE_MS)
    _, buf = recv_until(uart, buf, lambda m: False, REJOIN_GRACE_MS,
        on_msg=lambda m: on_device_joined(m) if m.get("op") == "device_joined" else None)

    if devices:
        ieee = list(devices.keys())[0]
        short = devices[ieee]["short_addr"]
        ep = devices[ieee]["ep"]
        print("\n[5] restored from storage — skipping pairing")
        print("    device: ieee=%s short=%s ep=%d" % (ieee, short, ep))
    else:
        print("\n[5] no devices — opening network for join (120 s) ...")
        print("    >>> press the pair/join button on the Sonoff now <<<")
        send_cmd(uart, "permit_join", {"duration": 120})
        msg, buf = recv_until(uart, buf,
            lambda m: m.get("op") == "permit_join" and m.get("type") == "ack", RESP_TIMEOUT_MS)
        if not msg:
            print("RESULT FAIL: permit_join got no ack")
            return
        msg, buf = recv_until(uart, buf, lambda m: m.get("op") == "device_joined", JOIN_TIMEOUT_MS)
        if not msg:
            print("RESULT FAIL: no device joined within timeout")
            return
        on_device_joined(msg)
        ieee = list(devices.keys())[0]
        short = devices[ieee]["short_addr"]
        ep = devices[ieee]["ep"]

    # From here on, always catch rejoins live -> a stale short_addr from a
    # previous run (or a rejoin mid-test) must not silently break the test.
    catch_rejoin = lambda m: on_device_joined(m) if m.get("op") == "device_joined" else None

    short = devices[ieee]["short_addr"]
    ep = devices[ieee]["ep"]
    print("\n[6] enable_reporting short_addr=%s ep=%d ..." % (short, ep))
    send_cmd(uart, "enable_reporting", {"short_addr": short, "endpoint": ep})
    msg, buf = recv_until(uart, buf,
        lambda m: m.get("type") in ("ack", "error") and
                  (m.get("op") == "enable_reporting" or m.get("type") == "error"),
        RESP_TIMEOUT_MS, on_msg=catch_rejoin)
    if not msg:
        print("RESULT FAIL: enable_reporting got no ack")
        return
    if msg.get("type") == "error" and msg.get("payload", {}).get("code") == "unknown_device":
        print("    short_addr went stale (rejoin) — retrying with current address")
        short = devices[ieee]["short_addr"]
        send_cmd(uart, "enable_reporting", {"short_addr": short, "endpoint": ep})
        msg, buf = recv_until(uart, buf,
            lambda m: m.get("op") == "enable_reporting" and m.get("type") == "ack",
            RESP_TIMEOUT_MS, on_msg=catch_rejoin)
        if not msg:
            print("RESULT FAIL: enable_reporting retry got no ack")
            return

    print("\n[7] waiting for reporting_configured / reporting_failed (15 s) ...")
    msg, buf = recv_until(uart, buf,
        lambda m: m.get("op") in ("reporting_configured", "reporting_failed"), 15_000,
        on_msg=catch_rejoin)
    if not msg:
        print("RESULT FAIL: no reporting_configured/reporting_failed event")
        return
    if msg.get("op") == "reporting_failed":
        print("RESULT FAIL: bind failed —", msg.get("payload"))
        return
    if msg.get("payload", {}).get("status") != "ok":
        print("RESULT FAIL: config_report status not ok —", msg.get("payload"))
        return
    print("    reporting configured OK")

    print("\n[8] >>> flip the PHYSICAL switch on the Sonoff once, short press "
          "(waiting %d s) <<<" % (PHYSICAL_WAIT_MS // 1000))
    msg, buf = recv_until(uart, buf, lambda m: m.get("op") == "attribute_report",
        PHYSICAL_WAIT_MS, on_msg=catch_rejoin)
    if not msg:
        print("RESULT FAIL: no attribute_report received after physical switch flip")
        return
    p = msg.get("payload", {})
    print("    attribute_report: short_addr=%s ep=%s on_off=%s" % (
        p.get("short_addr"), p.get("endpoint"), p.get("on_off")))

    print("\nRESULT PASS: attribute report arrived without polling")


main()
