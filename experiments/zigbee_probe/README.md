# Zigbee Probe

Disposable hardware proof-of-life code for the Zigbee coordinator firmware and
its MicroPython-side probes. Two hardware profiles share the same firmware and
protocol:

- Product A: CrowPanel Advance ESP32-S3 + ESP32-H2 wireless module slot.
- Product B: M5Stack AtomS3 Lite + M5 NanoC6 over a Grove HY2.0-4P cable.

This experiment is intentionally separate from the product app. It is the
current source of truth for hardware behavior that actually ran on real devices.

## Proven Slot Mapping (CrowPanel / H2)

- S3 GPIO5 -> H2 GPIO2
- H2 GPIO24 -> S3 GPIO19
- Baud: 115200
- S3 UART: UART1
- H2 UART: UART1

## Grove Mapping (AtomS3 Lite / NanoC6)

The Grove cable is straight through (white G1<->G1, yellow G2<->G2, red 5V,
black GND); the TX/RX cross happens in software via the GPIO matrix:

- AtomS3 G2 (TX, yellow) -> NanoC6 GPIO2 (RX)
- NanoC6 GPIO1 (TX, white) -> AtomS3 G1 (RX)
- Power: NanoC6 is fed 5V from the Atom's Grove pin (both can also be
  USB-powered independently; GND is shared through the cable either way).
- Baud/UART: same as H2 — UART1, 115200.
- Set `PROFILE = "atom_nano"` at the top of `tools/s3_zigbee_probe.py`.

NanoC6 hardware facts (docs.m5stack.com): ESP32-C6FH4, 4MB flash, native
USB-Serial/JTAG (no bridge chip). Download mode: hold the GPIO9 button while
plugging in USB. Grove: white=GPIO1, yellow=GPIO2.

Gate 1 result: S3 and H2 exchanged CRC-framed JSON over the slot UART.

Gate 2 result: the H2 coordinator formed/restored a Zigbee network, allowed one
real device to join, accepted `on_off` commands, and answered `read_attr` for
the OnOff attribute.

## Current Protocol

Frames are UTF-8 lines:

```text
<8 lowercase hex crc32> <json>\n
```

S3 commands currently sent by the probes:

- `ping`
- `permit_join` with `payload.duration`
- `on_off` with `payload.state` set to `on` or `off`
- `read_attr`
- `enable_reporting` with `payload.short_addr` and `payload.endpoint` — binds
  the device's OnOff cluster to this coordinator and configures ZCL
  attribute reporting (Gate 3, untested on hardware as of 0.6.0)

H2 messages currently emitted:

- `event` / `boot`
- `event` / `network_formed`
- `event` / `device_joined`
- `event` / `permit_join_status`
- `event` / `reporting_configured` — async result of `enable_reporting`,
  after bind succeeds and config_report is sent
- `event` / `reporting_failed` — async result of `enable_reporting` if bind
  fails
- `event` / `attribute_report` — unsolicited push when the device's OnOff
  state changes (e.g. physical switch press), once reporting is configured
- `ack` / `ping`
- `ack` / `permit_join`
- `ack` / `on_off`
- `ack` / `read_attr`
- `ack` / `enable_reporting` — only confirms the bind request was issued,
  not that reporting is active yet; wait for `reporting_configured`
- `error` with an error code in `payload.code`

## Pieces

- `h2_coordinator_firmware/` - ESP-IDF firmware for ESP32-H2 / ESP32-C6
  (target picked at build time; UART pins come from
  `sdkconfig.defaults.<target>`).
- `tools/s3_zigbee_probe.py` - MicroPython script for the S3 REPL.
- `tools/s3_ui_probe.py` - simple LVGL MicroPython UI probe.
- `tools/build_h2_coordinator.ps1` - build helper that copies source to
  `C:\tmp` before invoking ESP-IDF from WSL.
- `tools/flash_h2_coordinator.ps1` - flash and verify helper.

Generated ESP-IDF artifacts are intentionally ignored:

- `h2_coordinator_firmware/build/`
- `h2_coordinator_firmware/sdkconfig`

The clean build source is:

- `h2_coordinator_firmware/CMakeLists.txt`
- `h2_coordinator_firmware/sdkconfig.defaults`
- `h2_coordinator_firmware/partitions.csv`
- `h2_coordinator_firmware/main/`

## Build the H2 Coordinator

The repository path contains `&` in `smart&kosher`. ESP-IDF can configure from
that path, but some bootloader build commands may break on the `&`. Use the
helper so the actual build happens under `C:\tmp`.

```powershell
# ESP32-H2 (default)
.\experiments\zigbee_probe\tools\build_h2_coordinator.ps1

# M5 NanoC6
.\experiments\zigbee_probe\tools\build_h2_coordinator.ps1 -Target esp32c6
```

This creates (H2 keeps the legacy path, C6 gets its own):

```text
C:\tmp\h2_coordinator_flash\...          # esp32h2
C:\tmp\coordinator_flash_esp32c6\...     # esp32c6
```

each containing `bootloader.bin`, `partition-table.bin`,
`smart_kosher_h2_coordinator.bin`.

## Flash the Coordinator

With the module connected directly to the PC (NanoC6: hold the GPIO9 button
while plugging in USB to force download mode if needed):

```powershell
# H2
.\experiments\zigbee_probe\tools\flash_h2_coordinator.ps1 -Port COM6

# NanoC6
.\experiments\zigbee_probe\tools\flash_h2_coordinator.ps1 -Port COM7 -Chip esp32c6
```

## Run the S3 Probe

With the S3 connected to the PC and the H2 inserted in the wireless module slot,
copy/run `tools/s3_zigbee_probe.py` on the S3 MicroPython environment.

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

## Current Limits

- The H2 app keeps one runtime peer in `s_peer_short`.
- The Zigbee stack uses the `zb_storage` NVS partition, so the network itself
  can restore, but the app-level device list is not persisted yet.
- Multiple joined devices are not represented as first-class records.
- `read_attr` has one pending request slot.
- `on_off` can target an explicit `payload.short_addr`, but the probes do not
  yet exercise multiple targets.
- There is no H2-side idempotency for product `event_id` yet.

## Next Gate

Before promoting any hardware gateway into `src/`:

1. Replace `s_peer_short` with a small device table.
2. Persist the known device table in NVS.
3. Restore known devices after reset and expose them through `ping` or a new
   `list_devices` command.
4. Update the S3 probe to command a selected `short_addr`.
5. Verify two devices can be joined and controlled independently.
