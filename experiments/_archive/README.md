# Archived experiments

Nothing is kept here any more. This file remains as the provenance record for
where the panel's display code came from, because the question ("what happened
to the C firmware?") outlives the code itself.

## The display lineage, oldest to current

1. `crowpanel_ui/` — early LVGL-on-CrowPanel exploration: a Hebrew/RTL rendering
   probe, an Atom Echo echo test, and the `.bin` MicroPython fonts.
   Archived 2026-07-27, **deleted 2026-08-12**.
   `panel_mp/fonts/` carries its own byte-identical copies of those fonts, so
   nothing depended on this directory at the time it went.
2. `panel/` — the ESP-IDF firmware in C that `crowpanel_ui/` matured into.
   **Deleted 2026-08-05**, once MicroPython rendering was proven stable.
3. [`panel_mp/`](../../panel_mp/) — current. `display.py` is the direct
   descendant of `crowpanel_ui/hebrew_probe.py` (Hebrew/RTL/touch verified on
   the board 2026-07-16).

All three are recoverable from git history; the C firmware also lives on the
`panel-c-firmware` branch.

Still-active experiments live one level up in `experiments/` — notably
`zigbee_probe/`, which despite its name holds the **live production firmware**
for the H2/NanoC6 Zigbee coordinator, and is the documented path for flashing it.
