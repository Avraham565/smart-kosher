# Hardware bring-up for CrowPanel Advance 7" (ESP32-S3, RGB 800x480) under
# lvgl_micropython. Extracted from the proven experiments/_archive/crowpanel_ui/
# hebrew_probe.py path (Hebrew/RTL/touch verified on this exact board 2026-07-16).
#
# RENDERING NOTE — this is the whole point of the port. The RGB panel has no
# GRAM: the ESP32 re-streams the framebuffer from PSRAM every frame, so a PSRAM
# latency spike starves the DMA and the image drifts/jitters — even at idle.
#
# The bounce-buffer equivalent in lvgl_micropython is the PARTIAL-buffer path:
# leave frame_buffer1/2 unset and the driver allocates small (~1/10 screen)
# LVGL draw buffers, preferring INTERNAL SRAM + DMA, and keeps the two real full
# framebuffers hidden in C, copying partial renders into them on the second core
# (display_driver_framework: len(buf) != full_size => RENDER_MODE.PARTIAL). That
# decouples LVGL rendering from the LCD scanout the same way esp_lcd bounce
# buffers do in the C firmware. Passing two FULL framebuffers (the old path)
# forces RENDER_MODE.FULL = direct PSRAM scanout = the jitter we measured.
#
# Paired firmware config (boards/.../sdkconfig.rgbpanel): 64B data cache line +
# SPIRAM XIP. PCLK 12.5 MHz is the lvgl_micropython maintainer's value for this
# exact 800x480 panel class (discussion #511).

import lcd_bus
import lvgl as lv
import rgb_display
from machine import I2C, Pin

# --- pin map (validated on this board) --------------------------------------
_RGB_DATA = [
    21, 47, 48, 45, 38,       # B0-B4
     9, 10, 11, 12, 13, 14,   # G0-G5
     7, 17, 18,  3, 46,       # R0-R4
]
_HSYNC, _VSYNC, _DE, _PCLK = 40, 41, 42, 39
_I2C_SDA, _I2C_SCL = 15, 16
_BL_ADDR, _BL_BIT = 0x30, 1
_TOUCH_ADDR = 0x5D

# --- the rendering knob under test ------------------------------------------
PCLK_HZ = 18_000_000          # toward the C firmware's range; bounce buffers
                              # now absorb the extra PSRAM demand
_W, _H = 800, 480

# The shared I2C0 bus (backlight expander 0x30, touch 0x5D, PCF8563 RTC 0x51),
# published by init() so the RTC adapter reuses this instance instead of
# re-initialising the peripheral.
i2c = None


def _backlight_on(i2c):
    # STC8H1K28 expander (TCA9534-style): reg 3 = config (0x00 -> all outputs),
    # reg 1 = output latch.
    i2c.writeto_mem(_BL_ADDR, 3, bytes([0x00]))
    i2c.writeto_mem(_BL_ADDR, 1, bytes([1 << _BL_BIT]))


def _init_panel():
    p = _RGB_DATA
    bus = lcd_bus.RGBBus(
        hsync=_HSYNC, vsync=_VSYNC, de=_DE, pclk=_PCLK,
        data0=p[0],   data1=p[1],   data2=p[2],   data3=p[3],
        data4=p[4],   data5=p[5],   data6=p[6],   data7=p[7],
        data8=p[8],   data9=p[9],   data10=p[10], data11=p[11],
        data12=p[12], data13=p[13], data14=p[14], data15=p[15],
        freq=PCLK_HZ,
        # porches/polarity that came up clean on this board (8/8/4; SC7277
        # samples on the falling edge => pclk_active_low=True).
        hsync_front_porch=8, hsync_back_porch=8, hsync_pulse_width=4,
        vsync_front_porch=8, vsync_back_porch=8, vsync_pulse_width=4,
        hsync_idle_low=False, vsync_idle_low=False,
        de_idle_high=False, pclk_idle_high=False, pclk_active_low=True,
    )
    # No manual framebuffers: leaving them unset makes the driver allocate small
    # ~1/10-screen PARTIAL draw buffers (INTERNAL SRAM + DMA preferred) and keep
    # the two real full framebuffers hidden in C, copying into them on core 2 —
    # the bounce-buffer-equivalent staging that decouples rendering from scanout.
    disp = rgb_display.RGBDisplay(
        data_bus=bus,
        display_width=_W, display_height=_H,
        color_space=lv.COLOR_FORMAT.RGB565,
        rgb565_byte_swap=False,
    )
    disp.set_power(True)
    disp.init()
    return disp


class _I2CWrapper:
    # GT911 driver wants device.write_mem()/write_readinto(), not machine.I2C.
    def __init__(self, i2c, addr):
        self._i2c = i2c
        self._addr = addr

    def write_mem(self, reg, buf):
        self._i2c.writeto(self._addr, bytes([reg >> 8, reg & 0xFF]) + bytes(buf))

    def write_readinto(self, tx, rx):
        self._i2c.writeto(self._addr, bytes(tx), False)
        self._i2c.readfrom_into(self._addr, rx)


def init():
    """Backlight + RGB panel + GT911 touch. Returns the lv.display. Touch
    failure is non-fatal (UI still renders) so it never blocks the drift test.
    Publishes the I2C bus as ``display.i2c`` for the RTC adapter to reuse."""
    global i2c
    i2c = I2C(0, sda=Pin(_I2C_SDA), scl=Pin(_I2C_SCL), freq=400_000)
    _backlight_on(i2c)
    disp = _init_panel()
    try:
        import gt911
        gt911.GT911(device=_I2CWrapper(i2c, _TOUCH_ADDR), reset_pin=None,
                    interrupt_pin=None, startup_rotation=lv.DISPLAY_ROTATION._0)
        print("touch OK")
    except Exception as exc:
        print("touch init skipped:", exc)
    return disp
