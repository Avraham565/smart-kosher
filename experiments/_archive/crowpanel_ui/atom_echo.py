"""
atom_echo.py — Step 2 of the panel<->hub link bring-up (Grove edition).

The Elecrow UART cable from the panel's UART1-OUT sits in the Atom's
Grove PORT.A. VERIFIED crossing on hardware 2026-07-21:
    Atom RX = G2   (<- panel IO20-TX1)
    Atom TX = G1   (-> panel IO19-RX1)
Echoes every byte; the panel footer turns green once its SKLOOP frames
come back.

Power: for this step the Atom is USB-powered (3V3 wire disconnected).
Grove 5V pin -> SY8089 buck (2.5V min input) is the path for later
panel-powered operation.

Install as main.py via USB, then USB off, Grove cable in.
"""

import time
from machine import UART, Pin

RX_PIN = 2   # Grove G2
TX_PIN = 1   # Grove G1

uart = UART(1, baudrate=115200, tx=Pin(TX_PIN), rx=Pin(RX_PIN),
            timeout=0, rxbuf=1024)
print("atom_echo: UART1 up (rx=G%d tx=G%d) — echoing" % (RX_PIN, TX_PIN))

frames = 0
last_report = time.ticks_ms()

while True:
    data = uart.read()
    if data:
        uart.write(data)
        if b"SKLOOP" in data:
            frames += 1
    now = time.ticks_ms()
    if time.ticks_diff(now, last_report) > 5000:
        print("alive, frames=%d" % frames)
        last_report = now
    time.sleep_ms(10)
