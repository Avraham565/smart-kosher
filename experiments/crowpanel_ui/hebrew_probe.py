"""
hebrew_probe.py — Hebrew/RTL smoke test on CrowPanel Advance 7"
experiments/crowpanel_ui/

Requires firmware built with LV_USE_BIDI=1 and LV_FONT_DEJAVU_16_PERSIAN_HEBREW=1
(see s3_ui_probe.py header for build/flash procedure).

Upload (after removing old main.py per the documented DMA-safe procedure):
  python -m mpremote connect COM7 cp experiments/crowpanel_ui/fonts/assistant_20.bin :assistant_20.bin
  python -m mpremote connect COM7 cp experiments/crowpanel_ui/fonts/assistant_sb_28.bin :assistant_sb_28.bin
  python -m mpremote connect COM7 cp experiments/crowpanel_ui/hebrew_probe.py :main.py + reset

Pass criteria, verified visually on the panel:
  1. Hebrew letters render (not tofu boxes)
  2. Letter order is correct: title reads שלום עולם right-to-left
  3. Mixed text keeps digits inline: "3 דולקים מתוך 5"
  4. RTL base dir: labels align right, list rows mirror
  5. Title row renders in Assistant (runtime binfont) — visibly nicer than DejaVu
"""

import time
from machine import I2C, Pin
import lcd_bus
import rgb_display
import lvgl as lv
import task_handler

_RGB_DATA = [
    21, 47, 48, 45, 38,       # B0-B4
     9, 10, 11, 12, 13, 14,   # G0-G5
     7, 17, 18,  3, 46,       # R0-R4
]
_HSYNC, _VSYNC, _DE, _PCLK = 40, 41, 42, 39
_FREQ = 14_000_000            # SC7277 max safe
_TOUCH_SDA, _TOUCH_SCL = 15, 16
BL_ADDR, BL_BIT = 0x30, 1


def _backlight_on(i2c):
    i2c.writeto_mem(BL_ADDR, 3, bytes([0x00]))
    i2c.writeto_mem(BL_ADDR, 1, bytes([1 << BL_BIT]))


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
    # Two FULL-screen frame buffers in SPIRAM => LVGL RENDER_MODE.FULL with
    # direct buffer swap (zero copy). Proven stable 24h on the same-class
    # Waveshare S3 800x480 RGB board (lvgl_micropython discussion #333);
    # PARTIAL mode goes through the per-region copy path, which both starves
    # PSRAM bandwidth and exercises historically buggy rotation-copy code.
    FULL = 800 * 480 * 2
    buf1 = bus.allocate_framebuffer(FULL, lcd_bus.MEMORY_SPIRAM)
    buf2 = bus.allocate_framebuffer(FULL, lcd_bus.MEMORY_SPIRAM)
    disp = rgb_display.RGBDisplay(
        data_bus=bus,
        display_width=800, display_height=480,
        frame_buffer1=buf1, frame_buffer2=buf2,
        color_space=lv.COLOR_FORMAT.RGB565,
        rgb565_byte_swap=False,
    )
    disp.set_power(True)
    disp.init()
    return disp


def _no_scroll(obj):
    obj.remove_flag(lv.obj.FLAG.SCROLLABLE)


def _hebrew_font():
    f = getattr(lv, "font_dejavu_16_persian_hebrew", None)
    if f is None:
        print("FAIL: font_dejavu_16_persian_hebrew missing from build!")
        f = lv.font_montserrat_16
    return f


_assistant_fonts = {}   # keep refs alive — binfont must not be GC'd while in use
_fs_registered = False


def _load_assistant(path):
    """Load an lv_font_conv .bin font from the board VFS at runtime."""
    global _fs_registered
    if path in _assistant_fonts:
        return _assistant_fonts[path]
    try:
        import fs_driver
        if not _fs_registered:
            drv = lv.fs_drv_t()
            fs_driver.fs_register(drv, "S")
            _fs_registered = True
        font = lv.binfont_create("S:" + path)
        if font is None:
            raise ValueError("binfont_create returned None")
        _assistant_fonts[path] = font
        print("Assistant loaded:", path)
        return font
    except Exception as exc:
        print("Assistant load failed (%s): %s" % (path, exc))
        return None


def build_ui():
    heb = _hebrew_font()
    assistant = _load_assistant("assistant_sb_28.bin")
    scr = lv.screen_active()
    scr.set_style_bg_color(lv.color_hex(0x0D0D1A), lv.PART.MAIN)
    scr.set_style_base_dir(lv.BASE_DIR.RTL, lv.PART.MAIN)
    _no_scroll(scr)

    title = lv.label(scr)
    title.set_style_text_font(assistant or heb, lv.PART.MAIN)
    title.set_style_text_color(lv.color_hex(0xFFFFFF), lv.PART.MAIN)
    title.set_text("שלום עולם — בדיקת עברית על המסך"
                   + ("" if assistant else "  [DejaVu fallback]"))
    title.align(lv.ALIGN.TOP_MID, 0, 12)

    # mixed Hebrew + digits (the bidi acid test)
    mixed = lv.label(scr)
    mixed.set_style_text_font(heb, lv.PART.MAIN)
    mixed.set_style_text_color(lv.color_hex(0x7EC8E3), lv.PART.MAIN)
    mixed.set_text("3 דולקים מתוך 5 מכשירים")
    mixed.align(lv.ALIGN.TOP_MID, 0, 56)

    # RTL scrollable device list mimicking product B's — vertical scroll ONLY.
    # Rows live in a flex-column panel; each row is a fixed-height flex row.
    panel = lv.obj(scr)
    panel.set_size(720, 250)
    panel.set_pos(40, 104)
    panel.set_style_bg_color(lv.color_hex(0x0A0A14), lv.PART.MAIN)
    panel.set_style_border_width(0, lv.PART.MAIN)
    panel.set_style_radius(12, lv.PART.MAIN)
    panel.set_style_pad_all(8, lv.PART.MAIN)
    panel.set_style_pad_row(8, lv.PART.MAIN)
    panel.set_flex_flow(lv.FLEX_FLOW.COLUMN)
    panel.set_scroll_dir(lv.DIR.VER)          # kill any horizontal drift
    panel.set_scrollbar_mode(lv.SCROLLBAR_MODE.AUTO)

    names = ("דוד שמש", "מזגן סלון", "תאורת חדר מדרגות",
             "פלטת שבת", "מיחם", "מזגן חדר שינה",
             "תאורת חצר", "ונטה אמבטיה")
    for i, name in enumerate(names):
        row = lv.obj(panel)
        row.set_size(lv.pct(100), 56)
        row.set_style_bg_color(lv.color_hex(0x16213E), lv.PART.MAIN)
        row.set_style_border_width(0, lv.PART.MAIN)
        row.set_style_radius(10, lv.PART.MAIN)
        _no_scroll(row)

        lbl = lv.label(row)
        lbl.set_style_text_font(heb, lv.PART.MAIN)
        lbl.set_style_text_color(lv.color_hex(0xEEEEEE), lv.PART.MAIN)
        lbl.set_text(name)
        lbl.align(lv.ALIGN.RIGHT_MID, 0, 0)

        state = lv.label(row)
        state.set_style_text_font(heb, lv.PART.MAIN)
        on = i % 2 == 0
        state.set_style_text_color(
            lv.color_hex(0xFFB300 if on else 0x667788), lv.PART.MAIN)
        state.set_text("דולק" if on else "כבוי")
        state.align(lv.ALIGN.LEFT_MID, 0, 0)

    # Hebrew button — checks touch + pressed state with Hebrew label
    btn = lv.button(scr)
    btn.set_size(220, 72)
    btn.align(lv.ALIGN.BOTTOM_MID, 0, -24)
    btn.set_style_bg_color(lv.color_hex(0x0F3460), lv.PART.MAIN)
    blbl = lv.label(btn)
    blbl.set_style_text_font(heb, lv.PART.MAIN)
    blbl.set_text("לחץ עליי")
    blbl.center()

    def _clicked(e):
        blbl.set_text("נלחץ! " + str(time.ticks_ms() // 1000))
        print("button clicked")

    btn.add_event_cb(_clicked, lv.EVENT.CLICKED, None)


def main():
    i2c = I2C(0, sda=Pin(_TOUCH_SDA), scl=Pin(_TOUCH_SCL), freq=400_000)
    _backlight_on(i2c)
    _init_display()
    try:
        import gt911

        class _I2CWrapper:
            def __init__(self, i2c_, addr):
                self._i2c = i2c_
                self._addr = addr

            def write_mem(self, reg, buf):
                self._i2c.writeto(self._addr,
                                  bytes([reg >> 8, reg & 0xFF]) + bytes(buf))

            def write_readinto(self, tx, rx):
                self._i2c.writeto(self._addr, bytes(tx), False)
                self._i2c.readfrom_into(self._addr, rx)

        gt911.GT911(device=_I2CWrapper(i2c, 0x5D), reset_pin=None,
                    interrupt_pin=None,
                    startup_rotation=lv.DISPLAY_ROTATION._0)
        print("Touch OK")
    except Exception as exc:
        print("Touch init skipped:", exc)

    task_handler.TaskHandler()
    build_ui()
    print("Hebrew probe up — LVGL", lv.version_major(), lv.version_minor())


main()
