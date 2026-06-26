"""
s3_ui_probe.py  —  Zigbee UI on CrowPanel Advance 7"
experiments/zigbee_probe/tools/

═══════════════════════════════════════════════════════════════════════════════
STEP 0 — Build & flash firmware (do once, on a Linux/WSL/Mac build host):

  git clone https://github.com/lvgl-micropython/lvgl_micropython
  cd lvgl_micropython

  python3 make.py esp32 \\
    BOARD=ESP32_GENERIC_S3 BOARD_VARIANT=SPIRAM_OCT \\
    DISPLAY=rgb_display INDEV=gt911 \\
    --flash-size=8 --enable-uart-repl=y

  # Enter BOOT mode: hold BOOT + press RESET + release BOOT (screen goes black)
  python -m esptool --chip esp32s3 -p COM_PORT -b 460800 \\
    --before default_reset --after hard_reset \\
    write_flash --flash_mode dio --flash_size 8MB \\
    --flash_freq 80m --erase-all \\
    0x0 build/lvgl_micropy_ESP32_GENERIC_S3-SPIRAM_OCT-8.bin

  Verified LVGL version: 9.2.2 / MicroPython 1.24.1 (build 2025-04-26)

═══════════════════════════════════════════════════════════════════════════════
STEP 1 — Copy this file to the board via Thonny or mpremote:
  mpremote cp s3_ui_probe.py :main.py

═══════════════════════════════════════════════════════════════════════════════
Hardware map (CrowPanel Advance 7" V1.0 / V1.1):
  RGB  B0-B4  : GPIO 21, 47, 48, 45, 38
  RGB  G0-G5  : GPIO  9, 10, 11, 12, 13, 14
  RGB  R0-R4  : GPIO  7, 17, 18,  3, 46
  HSYNC=40  VSYNC=41  DE=42  PCLK=39  freq=21 MHz
  Touch GT911 : SDA=15  SCL=16
  Backlight   : I2C expander (TCA9534 or PCA9557; code scans + tries)
  UART→H2     : TX=5  RX=19  (no conflict with display)

  V1.2 / V1.3 note: backlight expander changed to STC8H1K28.
  If backlight stays off, check i2c_scan() output in REPL and adjust
  BL_ADDR / BL_BIT below.
"""

import json
import time
from machine import UART, I2C, Pin
import lcd_bus
import rgb_display
import lvgl as lv
import task_handler

# ─────────────────────────────────────────────────────────────────────────────
# Hardware constants
# ─────────────────────────────────────────────────────────────────────────────

# UART to H2 Zigbee coordinator
UART_ID   = 1
S3_TX_PIN = 5
S3_RX_PIN = 19
BAUD      = 115_200

# RGB display bus
_RGB_DATA = [
    21, 47, 48, 45, 38,       # B0-B4
     9, 10, 11, 12, 13, 14,   # G0-G5
     7, 17, 18,  3, 46,       # R0-R4
]
_HSYNC = 40
_VSYNC = 41
_DE    = 42
_PCLK  = 39
_FREQ  = 14_000_000           # 14 MHz; SC7277 max safe for lvgl_micropython RGB DMA

# GT911 touch
_TOUCH_SDA = 15
_TOUCH_SCL = 16

# Backlight I2C expander (TCA9534/PCA9557).
# I2C address 0x3C is the most common in Elecrow designs;
# 0x20 is TCA9534 default. Code will scan and warn if wrong.
BL_ADDR = 0x30  # found by I2C scan on this board (V1.2+, STC8H1K28)
BL_BIT  = 1    # which output pin of the expander drives backlight


# ─────────────────────────────────────────────────────────────────────────────
# CRC-32 + frame codec  (identical to s3_zigbee_probe.py)
# ─────────────────────────────────────────────────────────────────────────────

def _crc32(data: bytes) -> int:
    crc = 0xFFFF_FFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xEDB8_8320 if (crc & 1) else crc >> 1
            crc &= 0xFFFF_FFFF
    return crc ^ 0xFFFF_FFFF


def _encode(msg: dict) -> bytes:
    body = json.dumps(msg)
    crc  = _crc32(body.encode())
    return ("%08x %s\n" % (crc, body)).encode()


def _decode(line: bytes) -> dict:
    text = line.decode().strip()
    if len(text) < 10 or text[8] != " ":
        raise ValueError("not a frame")
    if int(text[:8], 16) != _crc32(text[9:].encode()):
        raise ValueError("crc mismatch")
    return json.loads(text[9:])


_seq = 0

def _send(uart, op: str, payload: dict = None):
    global _seq
    _seq += 1
    msg = {"version": 1, "type": "command", "op": op,
           "request_id": "ui-%s-%d" % (op, _seq)}
    if payload:
        msg["payload"] = payload
    uart.write(_encode(msg))


# ─────────────────────────────────────────────────────────────────────────────
# Backlight init via I2C expander
# ─────────────────────────────────────────────────────────────────────────────

def _backlight_on(i2c: I2C):
    devices = i2c.scan()
    if BL_ADDR not in devices:
        print("BL expander not at 0x%02x — scan found: %s" %
              (BL_ADDR, [hex(d) for d in devices]))
        # Try each found device as TCA9534-style expander (reg3=config, reg1=out)
        for addr in devices:
            try:
                i2c.writeto_mem(addr, 3, bytes([0x00]))          # all outputs
                i2c.writeto_mem(addr, 1, bytes([1 << BL_BIT]))   # set BL bit
            except OSError:
                pass
        return
    i2c.writeto_mem(BL_ADDR, 3, bytes([0x00]))           # config: all outputs
    i2c.writeto_mem(BL_ADDR, 1, bytes([1 << BL_BIT]))    # output: set BL bit


# ─────────────────────────────────────────────────────────────────────────────
# Display + touch init
# ─────────────────────────────────────────────────────────────────────────────

def _init_display():
    pins = _RGB_DATA
    bus = lcd_bus.RGBBus(
        hsync=_HSYNC, vsync=_VSYNC, de=_DE, pclk=_PCLK,
        data0=pins[0],  data1=pins[1],  data2=pins[2],
        data3=pins[3],  data4=pins[4],  data5=pins[5],
        data6=pins[6],  data7=pins[7],  data8=pins[8],
        data9=pins[9],  data10=pins[10], data11=pins[11],
        data12=pins[12], data13=pins[13], data14=pins[14],
        data15=pins[15],
        freq=_FREQ,
        hsync_front_porch=8, hsync_back_porch=8, hsync_pulse_width=4,
        vsync_front_porch=8, vsync_back_porch=8, vsync_pulse_width=4,
        hsync_idle_low=False, vsync_idle_low=False,
        de_idle_high=False, pclk_idle_high=False, pclk_active_low=True,
    )
    # Two half-screen SPIRAM frame buffers for RGB double-buffering
    HALF = 800 * 480 * 2 // 2
    buf1 = bus.allocate_framebuffer(HALF, lcd_bus.MEMORY_SPIRAM)
    buf2 = bus.allocate_framebuffer(HALF, lcd_bus.MEMORY_SPIRAM)
    disp = rgb_display.RGBDisplay(
        data_bus=bus,
        display_width=800, display_height=480,
        frame_buffer1=buf1, frame_buffer2=buf2,
        color_space=lv.COLOR_FORMAT.RGB565,
        rgb565_byte_swap=False,
    )
    disp.set_power(True)
    disp.init()
    # set_backlight() works only if the driver owns a LEDC pin;
    # on CrowPanel it doesn't, so we drive the expander directly instead.
    return disp


class _I2CWrapper:
    """Wraps machine.I2C to provide the write_mem/write_readinto API
    expected by the lvgl_micropython GT911 driver."""
    def __init__(self, i2c, addr):
        self._i2c  = i2c
        self._addr = addr

    def write_mem(self, reg, buf):
        self._i2c.writeto(self._addr,
                          bytes([reg >> 8, reg & 0xFF]) + bytes(buf))

    def write_readinto(self, tx, rx):
        self._i2c.writeto(self._addr, bytes(tx), False)
        self._i2c.readfrom_into(self._addr, rx)


def _init_touch(i2c: I2C):
    try:
        import gt911
        dev = _I2CWrapper(i2c, 0x5D)
        touch = gt911.GT911(
            device=dev,
            reset_pin=None,
            interrupt_pin=None,
            startup_rotation=lv.DISPLAY_ROTATION._0,
        )
        print("Touch OK")
        return touch
    except Exception as exc:
        print("Touch init skipped:", exc)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# UI state
# ─────────────────────────────────────────────────────────────────────────────

_net_ch   = None   # str, e.g. "15"
_net_pan  = None   # str, e.g. "0xABCD"
_dev_addr = None   # str, e.g. "0x9F12"

_log_lines: list = []
_MAX_LOG   = 64   # lines kept in memory; only last 10 shown

# Widget references set by build_ui()
_status_lbl = None
_log_lbl    = None
_uart_inst     = None   # filled in main()
_uart_buf      = b""
_uart_start_ms = 0


def _log(text: str):
    ts = "%d" % (time.ticks_ms() // 1000)
    _log_lines.append("[%s] %s" % (ts, text))
    if len(_log_lines) > _MAX_LOG:
        del _log_lines[0]
    if _log_lbl is not None:
        _log_lbl.set_text("\n".join(_log_lines[-10:]))


def _refresh_status():
    if _status_lbl is None:
        return
    ch  = _net_ch   or "--"
    pan = _net_pan  or "--"
    dev = _dev_addr or "--"
    _status_lbl.set_text(
        "Network: ch %s  PAN: %s     Device: %s" % (ch, pan, dev)
    )


# ─────────────────────────────────────────────────────────────────────────────
# Zigbee event dispatcher
# ─────────────────────────────────────────────────────────────────────────────

def _handle(msg: dict):
    global _net_ch, _net_pan, _dev_addr
    op   = msg.get("op", "")
    mtyp = msg.get("type", "")
    p    = msg.get("payload") or {}

    if op == "boot":
        fw  = p.get("firmware", "?")
        ver = p.get("firmware_version", "?")
        _log("H2 booted  fw=%s %s" % (fw, ver))

    elif op == "network_formed":
        _net_ch  = str(p.get("channel", "?"))
        _net_pan = p.get("pan_id", "?")
        _log("Network up  ch=%s  pan=%s" % (_net_ch, _net_pan))
        _refresh_status()

    elif op == "device_joined":
        _dev_addr = p.get("short_addr", "?")
        _log("Device joined  addr=%s" % _dev_addr)
        _refresh_status()

    elif op == "ping" and mtyp == "ack":
        global _net_ch, _net_pan
        _boot_seen = True
        net_up = p.get("network_up")
        fw  = p.get("firmware", "")
        ver = p.get("firmware_version", "")
        _log("H2 alive  fw=%s%s  net=%s" % (fw, " "+ver if ver else "", net_up))
        if p.get("channel"):
            _net_ch = str(p["channel"])
        if p.get("pan_id"):
            _net_pan = p["pan_id"]
        peer = p.get("peer_addr", "")
        if peer and peer != "none":
            _dev_addr = peer
        _refresh_status()

    elif mtyp == "ack":
        _log("ACK  op=%s" % op)

    else:
        _log("EVT  %s" % json.dumps(msg)[:72])


# ─────────────────────────────────────────────────────────────────────────────
# UART poll timer (runs every 50 ms inside LVGL scheduler)
# ─────────────────────────────────────────────────────────────────────────────

_boot_seen    = False
_ping_sent_at = None   # ticks_ms when we sent fallback ping

def _uart_poll(timer):
    global _uart_buf, _boot_seen, _ping_sent_at, _uart_start_ms
    u = _uart_inst
    if u is None:
        return

    # If no boot event after 3 s, send a ping to find out if H2 is already up
    if not _boot_seen:
        now = time.ticks_ms()
        if _ping_sent_at is None and time.ticks_diff(now, _uart_start_ms) > 3000:
            _log("No boot event — pinging H2 …")
            _send(u, "ping")
            _ping_sent_at = now
        elif _ping_sent_at and time.ticks_diff(now, _ping_sent_at) > 5000:
            _log("H2 not responding — check UART wiring")
            _ping_sent_at = now   # retry every 5 s

    if u.any():
        _uart_buf += u.read()
    while b"\n" in _uart_buf:
        line, _uart_buf = _uart_buf.split(b"\n", 1)
        line = line.strip()
        if not line:
            continue
        try:
            msg = _decode(line)
            if msg.get("op") in ("boot", "ping"):
                _boot_seen = True
            _handle(msg)
        except Exception:
            try:
                _log("RAW " + line.decode("utf-8", "replace")[:60])
            except Exception:
                pass


# ─────────────────────────────────────────────────────────────────────────────
# Button callbacks
# ─────────────────────────────────────────────────────────────────────────────

def _on_connect(e):
    _log(">>> permit_join  duration=180")
    _send(_uart_inst, "permit_join", {"duration": 180})


def _on_on(e):
    _log(">>> on_off ON")
    _send(_uart_inst, "on_off", {"state": "on"})


def _on_off(e):
    _log(">>> on_off OFF")
    _send(_uart_inst, "on_off", {"state": "off"})


# ─────────────────────────────────────────────────────────────────────────────
# LVGL UI
# ─────────────────────────────────────────────────────────────────────────────
# Layout (800 × 480):
#   y=  0.. 43  status bar
#   y= 52..131  [CONNECT]  [ON]  [OFF]
#   y=140..479  log area

def _make_btn(parent, text: str, x: int, y: int, w: int,
              color: int, cb) -> lv.button:
    btn = lv.button(parent)
    btn.set_size(w, 72)
    btn.set_pos(x, y)
    btn.set_style_bg_color(lv.color_hex(color), lv.PART.MAIN)
    btn.set_style_bg_color(
        lv.color_hex(color ^ 0x101010), lv.PART.MAIN | lv.STATE.PRESSED
    )
    btn.set_style_radius(8, lv.PART.MAIN)
    btn.set_style_border_width(0, lv.PART.MAIN)
    lbl = lv.label(btn)
    lbl.set_style_text_font(lv.font_montserrat_16, lv.PART.MAIN)
    lbl.set_style_text_color(lv.color_hex(0xFFFFFF), lv.PART.MAIN)
    lbl.set_text(text)
    lbl.center()
    btn.add_event_cb(cb, lv.EVENT.CLICKED, None)
    return btn


def build_ui():
    global _status_lbl, _log_lbl

    scr = lv.screen_active()
    scr.set_style_bg_color(lv.color_hex(0x0D0D1A), lv.PART.MAIN)
    scr.remove_flag(lv.obj.FLAG.SCROLLABLE)

    # ── status bar ────────────────────────────────────────────────────────────
    bar = lv.obj(scr)
    bar.set_size(800, 44)
    bar.set_pos(0, 0)
    bar.set_style_bg_color(lv.color_hex(0x16213E), lv.PART.MAIN)
    bar.set_style_border_width(0, lv.PART.MAIN)
    bar.set_style_radius(0, lv.PART.MAIN)
    bar.set_style_pad_all(0, lv.PART.MAIN)
    bar.remove_flag(lv.obj.FLAG.SCROLLABLE)

    _status_lbl = lv.label(bar)
    _status_lbl.set_width(776)
    _status_lbl.set_long_mode(lv.label.LONG_MODE.CLIP)
    _status_lbl.set_style_text_color(lv.color_hex(0x7EC8E3), lv.PART.MAIN)
    _status_lbl.set_style_text_font(lv.font_montserrat_16, lv.PART.MAIN)
    _status_lbl.align(lv.ALIGN.LEFT_MID, 12, 0)
    _status_lbl.set_text("Network: --  PAN: --     Device: --")

    # ── buttons ───────────────────────────────────────────────────────────────
    BTN_Y = 52
    _make_btn(scr, "CONNECT",  30, BTN_Y, 230, 0x0F3460, _on_connect)
    _make_btn(scr, "ON",      285, BTN_Y, 220, 0x1A6B3C, _on_on)
    _make_btn(scr, "OFF",     540, BTN_Y, 220, 0x7B1414, _on_off)

    # ── log panel ─────────────────────────────────────────────────────────────
    panel = lv.obj(scr)
    panel.set_size(800, 340)
    panel.set_pos(0, 140)
    panel.set_style_bg_color(lv.color_hex(0x080810), lv.PART.MAIN)
    panel.set_style_border_width(0, lv.PART.MAIN)
    panel.set_style_radius(0, lv.PART.MAIN)
    panel.set_style_pad_all(10, lv.PART.MAIN)
    panel.remove_flag(lv.obj.FLAG.SCROLLABLE)

    _log_lbl = lv.label(panel)
    _log_lbl.set_width(778)
    _log_lbl.set_style_text_color(lv.color_hex(0x00E676), lv.PART.MAIN)
    _log_lbl.set_style_text_font(lv.font_montserrat_14, lv.PART.MAIN)
    _log_lbl.set_long_mode(lv.label.LONG_MODE.WRAP)
    _log_lbl.align(lv.ALIGN.TOP_LEFT, 0, 0)
    _log_lbl.set_text("")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    global _uart_inst

    # I2C for touch + backlight expander (shared bus, same pins)
    i2c = I2C(0, sda=Pin(_TOUCH_SDA), scl=Pin(_TOUCH_SCL), freq=400_000)
    _backlight_on(i2c)

    _init_display()
    _init_touch(i2c)

    # TaskHandler drives LVGL refresh via MicroPython internal scheduler
    task_handler.TaskHandler()

    build_ui()
    _refresh_status()
    _log("Ready — waiting for H2 boot …")

    # UART to H2 (timeout=0 → non-blocking reads in poll timer)
    _uart_inst = UART(UART_ID, baudrate=BAUD, tx=S3_TX_PIN, rx=S3_RX_PIN,
                      timeout=0, rxbuf=1024)
    _uart_start_ms = time.ticks_ms()

    # Poll UART every 50 ms inside the LVGL event loop
    lv.timer_create(_uart_poll, 50, None)


main()
