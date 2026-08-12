"""Gate 2 Zigbee probe -- persistence + rejoin recovery.

S3 is the state owner: persists device registry to /devices.json.
H2 is a pure execution arm: stateless between requests.

Boot flow:
  1. Load saved registry from /devices.json (if exists).
  2. Confirm H2 alive (boot event or ping fallback).
  3. Wait for network_formed.
  4. Grace period (8 s): collect device_joined events -> update short_addrs.
  5a. If devices known (restored): skip pairing -> go to ON/OFF test.
  5b. If no devices: open permit_join -> wait for device_joined -> save.
  6. on_off ON  -> verify via read_attr.
  7. on_off OFF -> verify via read_attr.
  8. remove_device -> verify + remove from file.
  9. Report RESULT PASS / FAIL.
"""

import json
import time
from machine import UART

# Hardware profile: pick the pins matching the board this script runs on.
#   "crowpanel_h2": CrowPanel Advance S3 <-> ESP32-H2 module slot (TX=5, RX=19)
#   "atom_nano":    AtomS3 Lite Grove <-> M5 NanoC6 Grove         (TX=2, RX=1)
# Grove cable is straight (G1<->G1 white, G2<->G2 yellow); the TX/RX cross is
# done in software: Atom TX=G2 -> NanoC6 RX=GPIO2, NanoC6 TX=GPIO1 -> Atom RX=G1.
PROFILE = "atom_nano"

UART_ID          = 1
if PROFILE == "atom_nano":
    S3_TX_PIN    = 2
    S3_RX_PIN    = 1
else:
    S3_TX_PIN    = 5
    S3_RX_PIN    = 19
BAUD             = 115200
JOIN_TIMEOUT_MS  = 120_000
RESP_TIMEOUT_MS  = 8_000
REJOIN_GRACE_MS  = 8_000
DEVICES_PATH     = "/devices.json"


# -- CRC-32 --------------------------------------------------------

def crc32(data):
    crc = 0xFFFFFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xEDB88320 if (crc & 1) else crc >> 1
            crc &= 0xFFFFFFFF
    return crc ^ 0xFFFFFFFF


# -- Frame codec ---------------------------------------------------

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


# -- Transport -----------------------------------------------------

_seq = 0


def send_cmd(uart, op, payload=None):
    global _seq
    _seq += 1
    msg = {"version": 1, "type": "command", "op": op,
           "request_id": "s3-%s-%d" % (op, _seq)}
    if payload:
        msg["payload"] = payload
    uart.write(encode_frame(msg))
    print("TX  op=%s rid=%s" % (op, msg["request_id"]))
    return msg["request_id"]


def recv_until(uart, buf, match_fn, timeout_ms, on_msg=None):
    """Read until match_fn(msg) is True or timeout.

    on_msg(msg) is called for every valid frame received (before match check),
    allowing side-effects like registry updates during a drain/grace loop.
    Returns (matched_msg_or_None, buf).
    """
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


# -- Device registry -----------------------------------------------
#
# devices: { ieee_addr_str: {"short_addr": "0x1234", "ep": 1} }

devices = {}


def save_devices():
    try:
        with open(DEVICES_PATH, "w") as f:
            json.dump(devices, f)
        print("    saved %d device(s) to %s" % (len(devices), DEVICES_PATH))
    except Exception as e:
        print("    save_devices error:", e)


def load_devices():
    try:
        with open(DEVICES_PATH, "r") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        return data
    except Exception:
        return {}


def on_device_joined(msg):
    p     = msg.get("payload", {})
    ieee  = p.get("ieee_addr")
    short = p.get("short_addr")
    ep    = p.get("endpoint", 1)
    if not (ieee and short):
        return
    if ieee in devices:
        old = devices[ieee]["short_addr"]
        devices[ieee]["short_addr"] = short
        devices[ieee]["ep"]         = ep
        if old != short:
            print("    rejoin: %s  short %s -> %s" % (ieee, old, short))
        else:
            print("    rejoin: %s  short=%s (unchanged)" % (ieee, short))
    else:
        devices[ieee] = {"short_addr": short, "ep": ep}
        print("    new device: %s  short=%s  ep=%d" % (ieee, short, ep))
    save_devices()


def on_device_removed(ieee):
    if ieee in devices:
        del devices[ieee]
        save_devices()
        print("    registry: removed %s" % ieee)


def verify_onoff(uart, buf, short, ep, expect):
    """Poll read_attr until the device reports the expected state.

    Some relays (Telink/Tuya based) update the OnOff attribute noticeably
    later than they switch the physical output, so a single read right
    after the command ack can return the stale value.
    """
    attempts = 5
    for i in range(attempts):
        send_cmd(uart, "read_attr", {"short_addr": short, "endpoint": ep})
        msg, buf = recv_until(uart, buf,
            lambda m: m.get("op") == "read_attr" and m.get("type") == "ack",
            RESP_TIMEOUT_MS)
        if msg:
            got = bool(msg.get("payload", {}).get("on_off"))
            if got == expect:
                return True, buf
            print("    attempt %d/%d: on_off=%s (expect %s), retrying ..."
                  % (i + 1, attempts, got, expect))
        else:
            print("    attempt %d/%d: read_attr timed out, retrying ..."
                  % (i + 1, attempts))
        time.sleep_ms(700)
    return False, buf


# -- Main probe ----------------------------------------------------

def main():
    global devices

    uart = UART(UART_ID, baudrate=BAUD, tx=S3_TX_PIN, rx=S3_RX_PIN, timeout=20)
    print("=== Gate 2 Zigbee probe (persistence + rejoin) started ===")
    buf = b""

    # -- 1. load saved registry ------------------------------------
    devices = load_devices()
    if devices:
        print("[1] loaded %d device(s) from %s" % (len(devices), DEVICES_PATH))
        for ieee, d in devices.items():
            print("    %s  short=%s  ep=%d" % (ieee, d["short_addr"], d["ep"]))
    else:
        print("[1] no saved devices -- fresh start")

    # -- 2. confirm H2 is alive + network status -------------------
    print("\n[2] waiting for H2 boot event (5 s) ...")
    net_already_up = False
    msg, buf = recv_until(uart, buf,
        lambda m: m.get("op") == "boot", 5_000)
    if msg:
        p = msg.get("payload", {})
        print("    H2 booted: %s %s" % (p.get("firmware"), p.get("firmware_version")))
    else:
        print("    no boot event -- H2 already running, trying ping ...")
        send_cmd(uart, "ping")
        pong, buf = recv_until(uart, buf,
            lambda m: m.get("op") == "ping" and m.get("type") == "ack", 8_000)
        if not pong:
            print("RESULT FAIL: H2 not responding")
            return
        p = pong.get("payload", {})
        net_already_up = bool(p.get("network_up"))
        print("    pong: net_up=%s  fw=%s %s" % (
            p.get("network_up"), p.get("firmware"), p.get("firmware_version")))

    # -- 3. wait for network_formed (skip if already up) -----------
    if net_already_up:
        print("\n[3] network already up (from ping) -- skipping wait")
    else:
        print("\n[3] waiting for network_formed (30 s) ...")
        msg, buf = recv_until(uart, buf,
            lambda m: m.get("op") == "network_formed", 30_000)
        if not msg:
            print("RESULT FAIL: Zigbee network did not form")
            return
        p = msg.get("payload", {})
        print("    network up  channel=%s  pan=0x%s  %s" % (
            p.get("channel"), p.get("pan_id"), p.get("note", "")))

    # -- 4. grace period -- collect rejoin events -------------------
    print("\n[4] grace period %d ms -- waiting for rejoins ..." % REJOIN_GRACE_MS)
    _, buf = recv_until(uart, buf,
        lambda m: False,
        REJOIN_GRACE_MS,
        on_msg=lambda m: on_device_joined(m) if m.get("op") == "device_joined" else None)
    if devices:
        print("    registry after grace: %d device(s)" % len(devices))
    else:
        print("    no rejoins -- registry empty")

    # -- 5. pair or restore ----------------------------------------
    if devices:
        ieee  = list(devices.keys())[0]
        short = devices[ieee]["short_addr"]
        ep    = devices[ieee]["ep"]
        print("\n[5] restored from storage -- skipping pairing")
        print("    device: ieee=%s  short=%s  ep=%d" % (ieee, short, ep))
    else:
        print("\n[5] no devices -- opening network for join (180 s) ...")
        send_cmd(uart, "permit_join", {"duration": 180})
        msg, buf = recv_until(uart, buf,
            lambda m: m.get("op") == "permit_join" and m.get("type") == "ack",
            RESP_TIMEOUT_MS)
        if not msg:
            print("RESULT FAIL: permit_join got no ack")
            return

        print("    press pair/join on your device now ...")
        msg, buf = recv_until(uart, buf,
            lambda m: m.get("op") == "device_joined",
            JOIN_TIMEOUT_MS)
        if not msg:
            print("RESULT FAIL: no device joined within timeout")
            return
        on_device_joined(msg)
        ieee  = list(devices.keys())[0]
        short = devices[ieee]["short_addr"]
        ep    = devices[ieee]["ep"]
        print("    device: ieee=%s  short=%s  ep=%d" % (ieee, short, ep))
        time.sleep_ms(1000)

    # -- 6. on_off ON ----------------------------------------------
    print("\n[6] sending on_off ON ...")
    send_cmd(uart, "on_off", {"state": "on", "short_addr": short, "endpoint": ep})
    msg, buf = recv_until(uart, buf,
        lambda m: m.get("op") == "on_off" and m.get("type") == "ack",
        RESP_TIMEOUT_MS)
    if not msg:
        print("RESULT FAIL: on_off ON got no ack")
        return
    time.sleep_ms(500)

    # -- 7. read_attr -- verify ON ----------------------------------
    print("\n[7] reading on_off attribute (expect True) ...")
    ok, buf = verify_onoff(uart, buf, short, ep, True)
    if not ok:
        print("RESULT FAIL: device never reported on_off=True")
        return
    print("    on_off = True OK")
    time.sleep_ms(500)

    # -- 8. on_off OFF ---------------------------------------------
    print("\n[8] sending on_off OFF ...")
    send_cmd(uart, "on_off", {"state": "off", "short_addr": short, "endpoint": ep})
    msg, buf = recv_until(uart, buf,
        lambda m: m.get("op") == "on_off" and m.get("type") == "ack",
        RESP_TIMEOUT_MS)
    if not msg:
        print("RESULT FAIL: on_off OFF got no ack")
        return
    time.sleep_ms(500)

    # -- 9. read_attr -- verify OFF ---------------------------------
    print("\n[9] reading on_off attribute (expect False) ...")
    ok, buf = verify_onoff(uart, buf, short, ep, False)
    if not ok:
        print("RESULT FAIL: device never reported on_off=False")
        return
    print("    on_off = False OK")

    print("\nRESULT PASS: on/off verified -- device stays joined for persistence test")


main()
