# Hardware Reality Audit

Date: 2026-06-27

This project was originally built before the hardware was available. From this
point on, hardware-facing code should be promoted from `experiments/` only after
it has been tested on real devices.

## Hardware-Proven Source

Keep `experiments/zigbee_probe/` as the current hardware truth.

Proven there:

- CrowPanel S3 to ESP32-H2 slot UART mapping:
  - S3 GPIO5 -> H2 GPIO2
  - H2 GPIO24 -> S3 GPIO19
  - UART1, 115200 baud
- CRC32 + JSON line framing works across the S3/H2 UART link.
- H2 coordinator firmware can form or restore a Zigbee network.
- S3 can send `permit_join`.
- One real Zigbee device can join.
- S3 can send `on_off` commands through H2.
- S3 can send `read_attr` and verify the OnOff attribute.

Known current hardware limits:

- The H2 firmware keeps only one active peer in `s_peer_short` at runtime.
- The Zigbee network is configured to use NVS storage, but the app-level peer
  list is not yet persisted separately.
- Multiple joined devices are not first-class yet.
- The Python product app does not yet have a production hardware gateway.

## Keep

These areas are hardware-independent or product logic that does not depend on
untested Zigbee assumptions:

- `src/smart_kosher/zmanim/`
- `src/smart_kosher/data/`
- `src/smart_kosher/domain/actions.py`
- `src/smart_kosher/domain/events.py`
- `src/smart_kosher/domain/schedules.py`
- `src/smart_kosher/domain/entities.py`
- `src/smart_kosher/domain/_values.py`
- `src/smart_kosher/application/planner.py`
- `src/smart_kosher/application/executor.py`
- `src/smart_kosher/application/recovery.py`
- `src/smart_kosher/application/crud_service.py`
- `src/smart_kosher/application/control_service.py`
- `src/smart_kosher/ports/repository.py`
- `src/smart_kosher/ports/journal.py`
- `src/smart_kosher/ports/clock.py`
- `src/smart_kosher/adapters/json_repository.py`
- `src/smart_kosher/adapters/memory_repository.py`
- `src/smart_kosher/adapters/uart_codec.py`
- `src/smart_kosher/web/` for local product UI and API iteration
- `dev_server.py` for local development
- `tests/test_zmanim.py`
- `tests/test_domain.py`
- `tests/test_planner.py`
- `tests/test_application.py`
- `tests/test_storage.py`
- `tests/test_web.py`
- `tests/test_routes.py`
- `tests/test_uart_codec.py`

## Deleted

These files described a production Zigbee gateway that was not validated by the
current hardware experiment and did not match the H2 coordinator protocol:

- `src/smart_kosher/adapters/zigbee_gateway.py`
- `tests/test_zigbee_gateway.py`

Reason: they used a planned `zcl_command` protocol with IEEE address and Zigbee
endpoint routing. The H2 firmware that actually ran on hardware currently
accepts `ping`, `permit_join`, `on_off`, and `read_attr`.

## Rewrite From Experiments

These product concepts are valid, but their hardware-facing implementation must
come from the experiment, not the deleted blind adapter:

- A Python/MicroPython S3 gateway adapter.
- Device discovery and registration from H2 `device_joined` events.
- Device selection by explicit `short_addr` at first, then by stable IDs after
  the hardware proves what addresses survive reboot.
- Multi-device support.
- H2-side idempotency using product `event_id`.
- A saved app-level device list for reset/reboot recovery.

## Review Later

These are not deletion candidates now, but should be revisited as hardware work
moves from experiments into the product:

- `src/smart_kosher/domain/devices.py`: keep the generic endpoint/group model,
  but do not require or trust `ieee_address`/`zigbee_endpoint` until hardware
  discovery proves the final identifiers.
- `src/smart_kosher/web/static/app.js`: useful for UI iteration, but endpoint
  forms still expose planned Zigbee fields. Replace those with discovered
  device data when the H2 reports multiple devices.
- `src/smart_kosher/web/wifi_ap.py`: reasonable embedded stub, but not yet
  tested on the final firmware image.
- `data-sheets/`: keep as local reference material. The tracked PDFs are large;
  if Markdown extracts are enough, remove PDFs in a separate repository hygiene
  pass.

## Next Hardware Step

Start inside `experiments/zigbee_probe/h2_coordinator_firmware/main/main.c`:

1. Replace `s_peer_short` with a small device table.
2. Persist the device table in NVS under the normal `nvs` partition or a small
   explicit namespace.
3. Restore and report known devices on boot/ping.
4. Accept `short_addr` in `on_off` and target that device.
5. Update `s3_zigbee_probe.py` to join two devices or simulate two known short
   addresses where possible, then verify independent ON/OFF.

Only after that should product code grow a new hardware gateway adapter.
