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

Every step of that has to be *confirmed*, not assumed, because this script's
"board clean" is the licence the caller uses to start copying files. It said so
on runs where main.py was still there (measured 6 of 6), for two reasons that
had to both be fixed:

  * the removal was written to the REPL and given a flat 0.3s. os.remove does
    not return its prompt in 0.3s here, and the hardware reset on the next line
    aborted it mid-command -- so the file survived. Commands now wait for the
    prompt that means "finished", and the removal is read back before the reset.
  * the guard that should have caught it read the boot output for 2.2s, looking
    for a sentinel main.py does not print until 7.0s in (measured). It could
    never fire. The board is now watched until it proves one way or the other.

Usage:  python clean_board.py COM8
"""

import sys
import time

import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM8"
BAUD = 115200

# What main.py prints once it is up -- the one sign that the removal below did
# not take. Pinned to products/panel/device/main.py:BOOT_SENTINEL by
# tests/test_boot_sentinel_is_in_sync.py, because the two files cannot import
# each other (this one runs on the host, that one only on the device) and the
# check that reads it is only reached when the removal FAILED. A successful
# deploy never exercises it, so a drift here would go unnoticed until the day it
# mattered: a board still rendering, reported clean, and the next copy racing the
# DMA into a corrupt VFS.
BOOT_SENTINEL = b"panel up"

# How long to watch the board after the final reset before giving a verdict. A
# clean board answers with its prompt in about a second; a board that still has
# main.py takes 7.0s to reach the sentinel (measured on this panel), so anything
# under that turns the check below into a formality that always passes.
BOOT_WATCH_S = 12.0


def reset(ser):
    """Pulse EN (RTS) low->high with IO0 (DTR) released, so the chip boots the
    firmware normally -- not the ROM download loader (which needs IO0 low)."""
    ser.dtr = False          # IO0 high  -> normal boot
    ser.rts = True           # EN low    -> hold in reset
    time.sleep(0.1)
    # Drop anything the previous session left in the buffer, while the chip is
    # still held in reset and cannot be adding to it. The caller reads straight
    # into a fresh `boot` after this and decides "clean" on a `>>> ` in it -- a
    # leftover prompt from the REPL commands above would answer that question
    # before the board ever did. Flushed here rather than after the release
    # because at this instant nothing new can be discarded by mistake.
    ser.reset_input_buffer()
    ser.rts = False          # EN high   -> run


def drain(ser):
    return ser.read(ser.in_waiting or 1)


def command(ser, line, timeout=5.0):
    """Send one REPL line and wait for the prompt that says it finished.

    The prompt is the only completion signal the friendly REPL gives. Waiting a
    fixed interval instead is what broke this script: `import os` answers in
    well under 0.15s, so it looked fine, while the os.remove line had not come
    back by 0.3s -- and the caller reset the board on top of it.
    """
    ser.write(line.encode("utf-8") + b"\r")
    deadline = time.time() + timeout
    out = b""
    while time.time() < deadline:
        out += drain(ser)
        if out.rstrip().endswith(b">>>"):
            return out
        time.sleep(0.02)
    return out


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
        # over the REPL -- auto-indent makes that fragile; short-circuit instead),
        # then read the directory back. Asking the board is the only thing that
        # actually knows: the echo of the removal line proves it was *typed*, not
        # that it ran, and that echo is what this used to report as success.
        command(ser, "import os")
        command(ser, "'main.py' in os.listdir() and os.remove('main.py')")
        answer = command(ser, "print('MAINPY', 'main.py' in os.listdir())")
        if b"MAINPY False" not in answer:
            print("clean_board: could not remove main.py -- the board would boot "
                  "into the UI and any copy would race the DMA. Board says:")
            print("   " + answer.decode("utf-8", "replace").strip()[-200:])
            sys.exit(1)
        print("clean_board: main.py removed (confirmed by the board)")

        # Reset again: with main.py gone the board lands on a bare REPL and never
        # starts the DMA, so the following file copies are DMA-safe. Watch until
        # the board proves which one it is, rather than for a fixed interval:
        #   the bare REPL prompt  -> nothing ran, this is the clean board we want
        #   the boot sentinel     -> main.py ran after all, and the DMA is live
        # A board running main.py never reaches a prompt (asyncio.run does not
        # return), so the prompt is positive proof and normally lands in ~1s --
        # while the sentinel it used to wait for arrives at 7.0s, three times
        # later than the 2.2s window that was supposed to catch it.
        reset(ser)
        boot = b""
        end = time.time() + BOOT_WATCH_S
        clean = False
        while time.time() < end:
            boot += drain(ser)
            if BOOT_SENTINEL in boot:
                break
            if b">>> " in boot:
                clean = True
                break
            time.sleep(0.05)
        if BOOT_SENTINEL in boot:
            print("clean_board: WARNING main.py still ran -- board not clean")
            sys.exit(1)
        if not clean:
            print("clean_board: the board never reached a REPL prompt in {}s -- "
                  "not proven clean, refusing to hand it over".format(
                      BOOT_WATCH_S))
            sys.exit(1)
        print("clean_board: board clean (no main.py, no DMA)")
    finally:
        ser.close()


main()
