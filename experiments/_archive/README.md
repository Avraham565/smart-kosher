# Archived experiments

Probes that already served their purpose and have been superseded by
production code. Kept for reference/history; not part of any build.

- `crowpanel_ui/` — early LVGL-on-CrowPanel exploration (Hebrew rendering
  probe, Atom Echo echo test, `.bin` MicroPython fonts). Archived 2026-07-27.
  It matured into an ESP-IDF firmware in C under `panel/`, which was itself
  superseded by [`panel_mp/`](../../panel_mp/) once MicroPython rendering was
  proven stable, and deleted on 2026-08-05 — recoverable from git history or
  the `panel-c-firmware` branch. The `.bin` fonts here are the ones
  `panel_mp/fonts/` still uses.

Still-active experiments live one level up in `experiments/` (e.g.
`zigbee_probe/`, the documented path for flashing the H2 coordinator).
