# Zigbee Probe

Small, disposable proof-of-life firmware and tools for the CrowPanel Advance
ESP32-S3 display and the ESP32-H2 wireless module slot.

This experiment is intentionally separate from the product firmware. Gate 1 is
now locked: the H2 runs our firmware and the S3 can exchange CRC-framed JSON
messages with it through the slot UART.

## Proven Slot Mapping

- S3 GPIO5 -> H2 GPIO2
- H2 GPIO24 -> S3 GPIO19
- Baud: 115200
- S3 UART: UART1
- H2 UART: UART1

Last known result:

```text
RESULT PASS: pong seen
```

The H2 probe now uses the proven fixed mapping. It no longer sweeps pins during
normal operation.

## Pieces

- `h2_probe_firmware/` - minimal ESP-IDF firmware for ESP32-H2.
- `tools/s3_micropython_probe.py` - run on the S3 MicroPython REPL over USB.
- `tools/pc_serial_probe.py` - optional direct PC serial probe for the H2.
- `tools/s3_tx_sweep_probe.py` - archived diagnostic tool from the pin-finding
  phase.

Generated ESP-IDF artifacts are intentionally ignored:

- `h2_probe_firmware/build/`
- `h2_probe_firmware/sdkconfig`

The source of truth for a clean build is `h2_probe_firmware/sdkconfig.defaults`.
Use the build helper below; it copies only the clean source files and
`sdkconfig.defaults` into a temporary build directory.

## Build the H2 Probe

The repository path contains `&` in `smart&kosher`. ESP-IDF can configure the
project from that path, but one bootloader build command may break on the `&`.
Use the helper script so the actual build happens under `C:\tmp`.

```powershell
.\experiments\zigbee_probe\tools\build_h2_probe.ps1
```

This creates:

```text
C:\tmp\h2_probe_flash\bootloader.bin
C:\tmp\h2_probe_flash\partition-table.bin
C:\tmp\h2_probe_flash\smart_kosher_h2_probe.bin
```

## Flash the H2 Probe

With the H2 connected directly to the PC as `COM6`:

```powershell
.\experiments\zigbee_probe\tools\flash_h2_probe.ps1 -Port COM6
```

## Final Gate 1 Test Through the S3 Slot

With the S3 connected to the PC and the H2 inserted in the wireless module slot:

```powershell
.\experiments\zigbee_probe\tools\run_s3_probe.ps1 -Port COM8 -Python C:\Python314\python.exe
```

Expected success:

```text
BOOT from H2: smart_kosher_h2_probe 0.2.0 mode=fixed_uart tx=24 rx=2
PONG from H2: request_id=s3-ping-1 current_rx_pin=2
RESULT PASS: boot and pong seen
```

If only `pong` is seen, the protocol still passed and the boot beacon was
probably missed. If only `boot` is seen, H2-to-S3 is alive but S3-to-H2 should
be checked again. If neither is seen, check flash target, slot position, and
COM ports.

## Optional Direct H2 Check

If the H2 is connected directly to the PC:

```powershell
python experiments\zigbee_probe\tools\pc_serial_probe.py --port COM6
```

Run the script self-test without hardware:

```powershell
python experiments\zigbee_probe\tools\pc_serial_probe.py --self-test
```

## Archived TX Sweep

The S3 TX sweep was used to discover the real slot mapping. Keep it only as a
fallback diagnostic if the hardware setup changes:

```powershell
.\experiments\zigbee_probe\tools\run_s3_tx_sweep_probe.ps1 -Port COM8 -Python C:\Python314\python.exe
```

The known-good discovery result was `active_s3_tx=5` with
`current_h2_rx_pin=2`.

## Gate 2

Do not integrate into the main project yet. The next small proof should add
minimal Zigbee coordinator behavior on top of this proven UART path:

1. Start coordinator on the H2.
2. Send `permit_join` from S3.
3. Join one real Zigbee device.
4. Send one `on/off` command.
5. Return `command_result` to S3.
