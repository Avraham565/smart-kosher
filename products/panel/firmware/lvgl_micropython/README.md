# The panel's firmware — patches against lvgl_micropython

Product A does not run stock lvgl_micropython. It runs upstream plus the two
patches here, and **the difference is not cosmetic**: without `rgb_bus.patch`
every partial redraw leaves a stale row at each flush-strip boundary, which on
the glass is a card ruled with evenly spaced lines.

Those patches lived only in a working tree on one developer's WSL install until
2026-08-27. A second checkout, a fresh clone, or a rebuild after a `git clean`
would have produced a panel that looks broken for reasons nothing in this repo
explained. They are here so that stops being true.

## What is patched

Upstream: `lvgl_micropython` at **d2d2646**, built under WSL.

### `rgb_bus.patch` — `ext_mod/lcd_bus/esp32_src/`

Three changes, two of them fixes and one of them Avraham's original bring-up
work from July:

1. **`bounce_buffer_size_px = width * 10`** (`rgb_bus.c`). July's fix for
   scanout drift: the LCD scans from internal SRAM refilled from PSRAM instead
   of reading the framebuffer straight out of PSRAM. Not new here, carried so
   the patch is the whole difference from upstream.

2. **`rotate0`: `y < y_end` → `y <= y_end`** (`rgb_bus_rotation.c`). The bug
   behind tasks 42, 48 and 49. `y_end` is LVGL's `area.y2` and is inclusive, so
   the loop copied one row too few and the last row of every flushed strip was
   never written — it kept whatever the framebuffer already held. A full-width
   area takes the fast path two lines above, which uses `+ 1` and is correct;
   that is why whole-screen redraws were always clean and only partial-width
   ones showed bands. Upstream already carries the same fix on the rotated
   branches as `y_end += 1; // removes black lines between blocks`; rotation 0
   never got it.

3. **Dirty-box resync instead of a whole-framebuffer memcpy**
   (`rgb_bus_rotation.c`). With two framebuffers the copy task presented the
   idle buffer and then brought the other one level with a 768,000-byte
   PSRAM-to-PSRAM `memcpy` after **every** refresh. Measured cost: 42–47ms on
   any redraw that started before the previous one finished, which in the
   product is most of them. It now accumulates the bounding box of the strips
   it copied and repairs only that. A press went from ~87ms to ~40ms.
   Rotation 0 only — the rotated paths write transposed coordinates, so the box
   in source terms is not the box in destination terms, and they fall back to
   the full copy.

`flags.double_fb = 1` is upstream's value and stays. It was set to 0 for part
of 2026-08-27 on the theory that a second framebuffer was what left the bands;
that was **falsified** — with one framebuffer the bands were unchanged, and all
it bought was a visible top-to-bottom tear. The comment in `rgb_bus.c` records
this so nobody repeats it.

### `lv_conf.patch` — `lib/lv_conf.h`

`LV_USE_BIDI 1` and `LV_FONT_DEJAVU_16_PERSIAN_HEBREW 1`. Hebrew and RTL do not
render without them.

## Building

```bash
cd ~/lvgl_micropython
git apply /path/to/products/panel/firmware/lvgl_micropython/rgb_bus.patch
git apply /path/to/products/panel/firmware/lvgl_micropython/lv_conf.patch
python3 make.py esp32 BOARD=ESP32_GENERIC_S3 BOARD_VARIANT=SPIRAM_OCT \
    DISPLAY=rgb_display INDEV=gt911 --flash-size=8 --enable-uart-repl=y
```

Also needs the sdkconfig fragment (`CONFIG_ESP32S3_DATA_CACHE_LINE_64B=y`,
`CONFIG_SPIRAM_XIP_FROM_PSRAM=y`) wired last in the board variant — bounce
buffers require the 64B cache line.

Output: `build/lvgl_micropy_ESP32_GENERIC_S3-SPIRAM_OCT-8.bin`.

**Save the binary you are replacing before you build.** The build overwrites
that path in place, and it is the only copy of what is currently on the board —
the same trap already recorded for the H2 coordinator.

```powershell
python -m esptool --chip esp32s3 -p COM7 -b 460800 write-flash --erase-all 0x0 <bin>
```

`--erase-all` wipes the board's filesystem, `/data` included — devices, zones,
schedules, settings. Copy `:/data` off first and put it back after
`deploy.ps1`; `run_common.restore_main` will not do it for you.

## Verifying

`run_hwtest_ui.py --probe-home-press` is the acceptance test for the row fix:
odd presses draw the card once, even presses twice, and they must look
**identical and both clean**. Before the fix they never did.

`--probe-display-buffers` counts what the flashed firmware actually allocates,
which is how the `double_fb` theory was checked against the running binary
rather than against the source on disk.
