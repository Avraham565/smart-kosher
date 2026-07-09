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
- **Gate 3 (2026-07-01):** `enable_reporting` — S3 can bind a joined device's
  OnOff cluster to the coordinator and configure ZCL attribute reporting.
  Confirmed end-to-end on real hardware: physically flipping the Sonoff's
  wired wall switch pushed a spontaneous `attribute_report` event to S3 with
  no polling required. Firmware `smart_kosher_h2_coordinator` 0.6.0.

Known current hardware limits:

- H2 is fully stateless — no device table, no RAM between requests. Per-request only: `s_pending_rid`/`s_pending_short` for async `read_attr` correlation.
- S3 owns the device registry (`devices` dict) — RAM only for now, not persisted across S3 reboot.
- Multiple joined devices are supported in the protocol; persistence is the next step.

## Production Gateway (2026-07-09)

The same firmware now also builds for the M5 NanoC6 (`esp32c6`) and passed
Gate 2+3 on product B hardware (AtomS3 Lite + NanoC6 over Grove, UART1
115200, Atom TX=G2 -> Nano GPIO2, Nano GPIO1 -> Atom RX=G1).

`src/smart_kosher/adapters/zigbee_gateway.py` is the production
DeviceGateway over this protocol — verified end-to-end on hardware through
the real product stack (deploy -> permit_join via `zigbee.permit_join` ->
device_joined persisted to `/data/zigbee_devices.json` + auto
enable_reporting -> `control.send` on/off/toggle -> executed + journaled ->
`attribute_report` updates live state in the background poll task).

Lesson from first device run: `json.dumps(msg, separators=..., ensure_ascii=...)`
raises `TypeError: extra keyword arguments given` on MicroPython — code that
is only "MicroPython-compatible in theory" (uart_codec was never exercised
on-device before) must still be proven on hardware.

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
- `data-sheets/`: keep as local reference material. The tracked PDFs are large;
  if Markdown extracts are enough, remove PDFs in a separate repository hygiene
  pass.

## Next Hardware Step

Architecture refactor done (v0.5.0):
- H2 is fully stateless — `s_devices[]` table removed entirely.
- S3 supplies both `ieee_addr` and `short_addr` with every `remove_device` command.
- `ping` returns only firmware/version/network_up — no device list.
- `read_attr` ack returns `short_addr` only (no `ieee_addr` — H2 doesn't know it).

Remaining steps before product adapter:
1. Persist `devices` dict on S3 to `/devices.json` (survive S3 reboot).
2. Add device names in S3 registry.
3. Multi-device probe test: join two devices, verify independent ON/OFF.
4. Only then grow a new hardware gateway adapter in `src/`.
