# Panel fonts — how the five `.bin` files are built

`theme.py:load_fonts()` loads these at runtime with `lv.binfont_create("S:<name>")`,
and `deploy.ps1` step 2 copies `fonts/*.bin` to the board root on every deploy. So
they ship with the product, and until 2026-08-28 nothing recorded where they came
from. This file is that record.

## The command

Tool: [`lv_font_conv`](https://github.com/lvgl/lv_font_conv) **1.5.3** (npm).

```sh
npm install lv_font_conv           # or: npx lv_font_conv@1.5.3 …
```

Every file uses the same ranges, the same depth, and no compression. Only
`--font` and `--size` change:

```sh
RANGES="-r 0x20-0x7E -r 0x5D0-0x5EA -r 0x5F3-0x5F4 -r 0x20AA -r 0x2013-0x2014"

lv_font_conv --font src/Assistant-Regular.ttf  $RANGES --size 16 --bpp 4 \
             --format bin --no-compress -o assistant_16.bin
lv_font_conv --font src/Assistant-Regular.ttf  $RANGES --size 20 --bpp 4 \
             --format bin --no-compress -o assistant_20.bin
lv_font_conv --font src/Assistant-Regular.ttf  $RANGES --size 28 --bpp 4 \
             --format bin --no-compress -o assistant_28.bin
lv_font_conv --font src/Assistant-SemiBold.ttf $RANGES --size 28 --bpp 4 \
             --format bin --no-compress -o assistant_sb_28.bin
lv_font_conv --font src/Assistant-SemiBold.ttf $RANGES --size 48 --bpp 4 \
             --format bin --no-compress -o assistant_sb_48.bin
```

`_sb_` is SemiBold. The sizes match the filenames, and `theme.py` maps them:
16 `small`, 20 `body`, 28 `title`, sb 28 `h1`, sb 48 `clock`.

## What the ranges cover

| Range | What | Glyphs |
|---|---|---|
| `0x20-0x7E` | printable ASCII | 95 |
| `0x5D0-0x5EA` | Hebrew alphabet, finals included | 27 |
| `0x5F3-0x5F4` | geresh `׳`, gershayim `״` | 2 |
| `0x2013-0x2014` | en dash `–`, em dash `—` | 2 |
| `0x20AA` | sheqel `₪` | 1 |

127 glyphs per file. There are **no LV_SYMBOL glyphs here** — `theme.py` takes
`FONTS.symbol` from the built-in `font_montserrat_28` instead. A character the UI
draws that is not in the table above renders as a box, which is what
`test_font_glyph_coverage` in `hwtest/hwtest_ui.py` exists to catch.

## The TTFs

`src/` holds the exact inputs, vendored so the recipe is reproducible rather than
merely written down. They are the static instances of Google Fonts **Assistant
v3.000**, taken from `google/fonts` at commit `89c9db015089`:

```
https://raw.githubusercontent.com/google/fonts/89c9db015089/ofl/assistant/static/Assistant-Regular.ttf
https://raw.githubusercontent.com/google/fonts/89c9db015089/ofl/assistant/static/Assistant-SemiBold.ttf
```

That commit is where the family became variable, so it is the **last** revision
carrying static instances — `ofl/assistant/` on `main` now ships only
`Assistant[wght].ttf`, and a static instance sliced out of the variable font is
not the same file. Licence: OFL 1.1, `src/OFL.txt`.

`src/` is not deployed. `deploy.ps1` step 2 globs `fonts\*.bin` without
`-Recurse`, and the orphan sweep in step 3c only considers `.py`.

## How this was verified, 2026-08-28

The argv was recovered from the repo's own history: `lv_font_conv` stamps its
command line into the header of every `.c` it emits, and commit `d416913`
("compile Assistant fonts (5 sizes) and use in hello UI") carries five of them
from the C-firmware era. That argv says `--format lvgl --lv-include lvgl.h`,
because it built C arrays rather than the `.bin` files loaded today.

So the recipe above was not copied — it was re-run and compared:

- Rebuilding all five from `src/` with the command above produces files
  **byte-identical** to the ones committed here (5340 / 7512 / 13484 / 13804 /
  37752 bytes, `cmp` clean on all five).
- Independently, parsing the committed `.bin` headers agrees on every parameter:
  `bpp=4`, compression flag 0, sizes 16/20/28/28/48, and a `cmap` holding exactly
  95 + 27 + 5 entries, the sparse five being U+05F3, U+05F4, U+2013, U+2014,
  U+20AA — one for one with the four small `-r` arguments.
- Mutation, to prove the comparison was live and not passing on everything:
  dropping `-r 0x20AA` alone yields 5288 bytes instead of 5340, and `cmp` fails.

Byte-identity depends on the tool version as well as the TTF. If a future
`lv_font_conv` reproduces these files, nothing needs saying; if it does not, the
version above is the one that does.
