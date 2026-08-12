# Zigbee Probes

Disposable hardware proof-of-life scripts for the Zigbee coordinator, run from
the MicroPython REPL on the hub side of the UART link. They are developer
tools: not shipped, not deployed to a board by any deploy script, and excluded
from production lint (`pyproject.toml`, `[tool.ruff] extend-exclude`).

The firmware they talk to is **not** disposable — it lives in
[`firmware/h2_coordinator/`](../../firmware/h2_coordinator/), which is also
where the wiring, the command set and the build/flash instructions are
documented.

Two hardware profiles share the same firmware and protocol:

- Product A: CrowPanel Advance ESP32-S3 + ESP32-H2 wireless module slot.
- Product B: M5Stack AtomS3 Lite + M5 NanoC6 over a Grove HY2.0-4P cable.

## Pieces

- `s3_zigbee_probe.py` - MicroPython script for the S3 REPL: joins a device and
  drives `on_off` / `read_attr`.
- `gate3_reporting_probe.py` - exercises `enable_reporting` and the unsolicited
  `attribute_report` push.
- `s3_ui_probe.py` - simple LVGL MicroPython UI probe.

Set `PROFILE = "atom_nano"` at the top of `s3_zigbee_probe.py` to target
product B instead of the CrowPanel slot.

## Run the S3 Probe

With the S3 connected to the PC and the H2 inserted in the wireless module slot,
copy/run `s3_zigbee_probe.py` on the S3 MicroPython environment.

Expected flow:

```text
H2 booted
network up
permit_join ack
user pairs one Zigbee device
device_joined
on_off ON ack
read_attr on_off=True
on_off OFF ack
read_attr on_off=False
RESULT PASS: device joined, on/off verified
```
