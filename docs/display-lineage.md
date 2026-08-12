# Display code lineage

This is the provenance record for where the panel's display code came from,
because the question ("what happened to the C firmware?") outlives the code
itself. It was `experiments/_archive/README.md` until that directory was
dissolved on 2026-08-12; nothing but this record was left in it by then.

## The display lineage, oldest to current

1. `crowpanel_ui/` — early LVGL-on-CrowPanel exploration: a Hebrew/RTL rendering
   probe, an Atom Echo echo test, and the `.bin` MicroPython fonts.
   Archived 2026-07-27, **deleted 2026-08-12**.
   `panel_mp/fonts/` carries its own byte-identical copies of those fonts, so
   nothing depended on this directory at the time it went.
2. `panel/` — the ESP-IDF firmware in C that `crowpanel_ui/` matured into.
   **Deleted 2026-08-05**, once MicroPython rendering was proven stable.
3. [`panel_mp/`](../panel_mp/) — current. `display.py` is the direct
   descendant of `crowpanel_ui/hebrew_probe.py` (Hebrew/RTL/touch verified on
   the board 2026-07-16).

All three are recoverable from git history; the C firmware also lives on the
`panel-c-firmware` branch.

The one thing under `experiments/` that was never disposable is the Zigbee
coordinator firmware. It is now [`firmware/h2_coordinator/`](../firmware/h2_coordinator/),
where its name matches what it is, and the MicroPython probes it was filed
beside are now [`tools/zigbee_probe/`](../tools/zigbee_probe/).
