# H2 Coordinator Firmware

ESP-IDF firmware for the Zigbee coordinator: ESP32-H2 in the CrowPanel's
wireless module slot (product A), or an M5 NanoC6 over a Grove cable
(product B). One firmware, one protocol, target picked at build time.

This is **live production firmware**, not a probe. It is what is flashed to the
coordinator that the shipping brain talks to. The exploratory MicroPython
scripts that were once its neighbours now live in [`tools/zigbee_probe/`](../../tools/zigbee_probe/).

The canonical protocol specification is [`docs/UART_PROTOCOL.md`](../../docs/UART_PROTOCOL.md).
The sections below record the wiring and the command set as proven on hardware;
where the two disagree, the protocol document wins.

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

- `main/` — the firmware sources (`protocol`, `link`, `txn`, `zb`, `main`).
- `host_test/` — the pure layers (protocol/txn) compiled and run on the host.
- `../tools/build_h2_coordinator.ps1` - build helper that copies source to
  `C:\tmp` before invoking ESP-IDF from WSL.
- `../tools/flash_h2_coordinator.ps1` - flash and verify helper.

Generated ESP-IDF artifacts are intentionally ignored:

- `build/`
- `sdkconfig`
- `managed_components/`

`dependencies.lock` is deliberately **not** ignored: it records the exact
esp-zigbee-lib build the firmware was verified against on hardware.

The clean build source is:

- `CMakeLists.txt`
- `sdkconfig.defaults`
- `partitions.csv`
- `main/`

## Build the H2 Coordinator

The repository path contains `&` in `smart&kosher`. ESP-IDF can configure from
that path, but some bootloader build commands may break on the `&`. Use the
helper so the actual build happens under `C:\tmp`.

```powershell
# ESP32-H2 (default)
.\firmware\tools\build_h2_coordinator.ps1

# M5 NanoC6
.\firmware\tools\build_h2_coordinator.ps1 -Target esp32c6
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
.\firmware\tools\flash_h2_coordinator.ps1 -Port COM6

# NanoC6
.\firmware\tools\flash_h2_coordinator.ps1 -Port COM7 -Chip esp32c6
```

## Host Tests

The pure layers build and run on the host with gcc, no hardware needed:

```bash
bash firmware/h2_coordinator/host_test/run.sh
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
