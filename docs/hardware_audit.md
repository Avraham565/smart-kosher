# Hardware Reality Audit

Date: 2026-06-27. Reviewed 2026-08-05.

This project was originally built before the hardware was available. From this
point on, hardware-facing code should be promoted from `experiments/` only after
it has been tested on real devices.

> **How to read this file.** It is a dated audit log, not a description of the
> present. Sections are appended, not rewritten, so an early section can be
> superseded by a later one — the `## Deleted` list below is the clearest case:
> the files it names were deleted in June 2026 and then *rebuilt* from the
> hardware-proven protocol in July, which `## Production Gateway (2026-07-09)`
> records. Each superseded section is now marked. For the current protocol read
> `docs/UART_PROTOCOL.md`; for the current firmware plan, `docs/h2_production_plan.md`.
>
> **Path note, 2026-08-12.** `experiments/` no longer exists. The coordinator
> firmware this file calls `experiments/zigbee_probe/h2_coordinator_firmware/`
> is now `firmware/h2_coordinator/`, and the MicroPython probes beside it are
> now `tools/zigbee_probe/`. The old paths are left in place below because this
> is a dated log, not a description of the present.

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

### Async redesign (2026-07-09, same day)

The whole command chain is now async end-to-end (gateway -> Executor ->
ControlService -> Api.dispatch -> HTTP routes / serial channel): no polling
sleeps anywhere. Inbound is one `asyncio.StreamReader(uart)` reader task;
each command awaits an `asyncio.Event` keyed by request_id, resolved the
moment its ack frame arrives. Verified on hardware.

- Ack timeout 1500ms (acks measured well under 500ms on hardware).
- Circuit breaker is **ping-verdict only**: a device command timing out is
  ambiguous (dead link vs dead device), so it fires a single background
  probe ping; only ping timeouts open the breaker, any inbound frame
  closes it. A silent device gets `unreachable: true` in `zigbee.devices`
  instead (cleared by its next report/rejoin).
- Toggle flips the live reported state when known — one round-trip;
  read_attr only on a cold cache.
- `control.send` accepts `confirm_ms`: after the ack, wait up to that long
  for the device's own attribute_report to say the state actually changed
  (`confirmation: {confirmed, observed}` in the result) — ACK level 4
  (observed_state) per the architecture decision. Proven on hardware:
  `confirmed: true` arrived from a real report.
- Field lesson: a device can drop off the mesh and keep its short_addr on
  rejoin; when the hub is down during the rejoin announce, device_joined
  is lost. A power-cycle of the device heals it. MicroPython quirk:
  `await` inside a list comprehension is a compile error (mpy-cross).

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
- `src/smart_kosher/application/migrations.py`
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
- `tests/test_zmanim_reference.py`
- `tests/test_cities.py`
- `tests/test_migrations.py`
- `tests/test_zman_keys_are_in_sync.py`
- `tests/test_domain.py`
- `tests/test_planner.py`
- `tests/test_application.py`
- `tests/test_storage.py`
- `tests/test_web.py`
- `tests/test_routes.py`
- `tests/test_uart_codec.py`

## Deleted (2026-06-27) — ⚠️ SUPERSEDED, both files exist again

> **Do not read this as current.** Both files below were deleted in June 2026
> and then written again from scratch in July against the protocol the hardware
> actually speaks. They exist today and are the production path — see
> `## Production Gateway (2026-07-09)` above. What stayed dead is the
> `zcl_command` design, not the filenames.

These files described a production Zigbee gateway that was not validated by the
current hardware experiment and did not match the H2 coordinator protocol:

- `src/smart_kosher/adapters/zigbee_gateway.py`
- `tests/test_zigbee_gateway.py`

Reason: they used a planned `zcl_command` protocol with IEEE address and Zigbee
endpoint routing. The H2 firmware that actually ran on hardware currently
accepts `ping`, `permit_join`, `on_off`, and `read_attr`.

## Rewrite From Experiments — ✅ done, except where noted

These product concepts are valid, but their hardware-facing implementation must
come from the experiment, not the deleted blind adapter:

- ✅ A Python/MicroPython S3 gateway adapter. — `adapters/zigbee_gateway.py`.
- ✅ Device discovery and registration from H2 `device_joined` events.
- ✅ Device selection by `short_addr`, keyed on the stable `ieee_addr`: the
  registry is healed from every `device_joined`, because short_addr changes on
  rejoin.
- ✅ Multi-device support. Multi-*gang* (several endpoints on one radio) is
  **not** done: the coordinator discovers and reports the endpoint list, and
  commands honour a per-entity `zigbee_endpoint`, but the hub's live state is
  still keyed by ieee alone, so two gangs of one switch share one state.
- ❌ H2-side idempotency using product `event_id`. Not implemented, and no
  longer the plan: the H2 is deliberately stateless, and delivery proof now
  comes from the APS confirm (`delivered`), so the hub journals only what
  actually arrived. The residual risk is power loss between the relay acting
  and the hub journalling.
- ✅ A saved app-level device list for reset/reboot recovery. —
  `/data/zigbee_devices.json`.

## Review Later

These are not deletion candidates now, but should be revisited as hardware work
moves from experiments into the product:

- `src/smart_kosher/domain/devices.py`: keep the generic endpoint/group model,
  but do not require or trust `ieee_address`/`zigbee_endpoint` until hardware
  discovery proves the final identifiers.
- `data-sheets/`: keep as local reference material. The tracked PDFs are large;
  if Markdown extracts are enough, remove PDFs in a separate repository hygiene
  pass.

## Next Hardware Step — ⚠️ SUPERSEDED (this describes firmware v0.5.0)

> Steps 1–4 below are all done. The coordinator is now at 0.11.x and the
> production plan lives in `docs/h2_production_plan.md`; its open items are the
> current list, not this one.

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
