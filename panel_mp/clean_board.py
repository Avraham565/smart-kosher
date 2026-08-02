"""Interrupt a CrowPanel out of a running (LVGL-DMA) main.py and delete main.py,
leaving a clean, DMA-free REPL -- the precondition deploy.ps1 needs before it
can copy files without racing the RGB DMA.

Why this exists: once main.py has started the RGB panel, the DMA re-streams the
framebuffer forever, even after main.py returns to the >>> prompt (TaskHandler)
or while the asyncio loop runs. mpremote's raw REPL + raw-paste then races that
DMA, and a large transfer corrupts the VFS -> Guru Meditation LoadProhibited
(fingerprint A#=0x0000cdcd; see memory panel-mp-rendering). So we cannot clean a
board that is already rendering.

Instead we hardware-reset the board and spam Ctrl-C through the boot/import
window, catching main.py *before* display.init() starts the DMA, remove main.py
at the friendly REPL, then reset again into a bare REPL that runs no main.py and
therefore no DMA.

Usage:  python clean_board.py COM8
"""

import sys
import time

import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM8"
BAUD = 115200


def reset(ser):
    """Pulse EN (RTS) low->high with IO0 (DTR) released, so the chip boots the
    firmware normally -- not the ROM download loader (which needs IO0 low)."""
    ser.dtr = False          # IO0 high  -> normal boot
    ser.rts = True           # EN low    -> hold in reset
    time.sleep(0.1)
    ser.rts = False          # EN high   -> run


def drain(ser):
    return ser.read(ser.in_waiting or 1)


def main():
    ser = serial.Serial(PORT, BAUD, timeout=0.05)
    try:
        print("clean_board: reset + interrupt on", PORT)
        reset(ser)

        # Spam Ctrl-C through the boot window to catch main.py before it starts
        # the display DMA. The top-of-main import of the brain package is a wide
        # window; a few seconds of Ctrl-C reliably lands inside it.
        deadline = time.time() + 6
        buf = b""
        at_prompt = False
        while time.time() < deadline:
            ser.write(b"\x03")
            time.sleep(0.02)
            buf += drain(ser)
            if b">>> " in buf[-16:]:
                at_prompt = True
                break
        ser.write(b"\r\x03\x03")
        time.sleep(0.2)
        drain(ser)
        print("clean_board: reached REPL" if at_prompt
              else "clean_board: prompt not confirmed, trying removal anyway")

        # Remove main.py without raising if it is already gone (no try/except
        # over the REPL -- auto-indent makes that fragile; short-circuit instead).
        ser.write(b"import os\r")
        time.sleep(0.15)
        ser.write(b"'main.py' in os.listdir() and os.remove('main.py')\r")
        time.sleep(0.3)
        print("clean_board: removed main.py ->", drain(ser).decode("utf-8", "replace").strip()[-60:])

        # Reset again: with main.py gone the board lands on a bare REPL and never
        # starts the DMA, so the following file copies are DMA-safe. Read for a
        # couple of seconds -- long enough that a still-present main.py would have
        # printed "panel_mp up" (it renders ~1-2s in).
        reset(ser)
        boot = b""
        end = time.time() + 2.2
        while time.time() < end:
            boot += drain(ser)
            time.sleep(0.05)
        if b"panel_mp up" in boot:
            print("clean_board: WARNING main.py still ran -- board not clean")
            sys.exit(1)
        print("clean_board: board clean (no main.py, no DMA)")
    finally:
        ser.close()


main()
