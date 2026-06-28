# Smart Kosher

Smart Kosher is an offline-first home automation core for reliable civil-time
and Jewish-calendar scheduling. The intended product uses a local wall-mounted
controller, requires no cloud service or smartphone, and prepares device
behavior for Shabbat and Jewish holidays.

The repository now has two kinds of truth:

- `src/` contains the tested, hardware-independent product core.
- `experiments/zigbee_probe/` contains the hardware-proven Zigbee/S3/H2 work.

Hardware-facing code should be promoted from `experiments/` only after it has
worked on real devices.

## Current Status

Implemented and tested in the Python product core:

- Offline Jewish calendar, holidays, Omer counting, weekly parasha, and zmanim.
- Deterministic event planning from fixed local times or calculated zmanim.
- Israeli daylight-saving-time resolution without an online service.
- Cross-midnight schedules and bounded catch-up after delayed execution.
- Validated domain models for schedules, actions, events, zones, endpoints,
  and groups.
- Idempotent execution with bounded retries, ACK handling, and an execution
  journal.
- JSON persistence with temporary files, backup recovery, and defensive copies.
- In-memory adapters and a deterministic gateway simulator for tests.

Hardware-proven in `experiments/zigbee_probe/`:

- CrowPanel S3 to ESP32-H2 slot UART mapping:
  - S3 GPIO5 -> H2 GPIO2
  - H2 GPIO24 -> S3 GPIO19
  - UART1, 115200 baud
- CRC32 + JSON line framing between S3 and H2.
- H2 coordinator firmware can form or restore a Zigbee network.
- S3 can send `permit_join`.
- One real Zigbee device can join.
- S3 can send `on_off` and verify state with `read_attr`.

Not implemented or not yet product-integrated:

- A production Python/MicroPython hardware gateway in `src/`.
- Multiple first-class Zigbee devices at the H2 firmware level.
- App-level persistence of the discovered device list after reset.
- H2-side idempotency using product `event_id`.
- Real RTC retention, watchdog, LVGL product UI, deployment, and power-loss
  behavior.

## Project Structure

```text
src/smart_kosher/
|-- zmanim/            Offline calendar and zmanim calculations
|-- domain/            Business models and validation rules
|-- application/       Planner, Executor, and RecoveryService
|-- ports/             Clock, Repository, Gateway, and Journal contracts
|-- adapters/          JSON, memory, and gateway simulator for tests
`-- data/              Packaged and validated city profiles

experiments/zigbee_probe/
|-- h2_coordinator_firmware/   ESP32-H2 coordinator firmware
`-- tools/                     S3 MicroPython probes and build/flash helpers

tests/                        Unit tests for the product core
data-sheets/                  Local device notes and vendor references
```

`src` is a source directory, not an import namespace:

```python
from smart_kosher.application.planner import Planner, PlannerConfig
from smart_kosher.data import get_city, load_cities
from smart_kosher.zmanim import compute_zmanim
```

## Architecture

The product core follows a lightweight Ports and Adapters structure:

```text
Repository -> Planner -> Event -> Executor -> DeviceGateway
                                      |
                                      v
                                EventJournal
```

- `zmanim` is independent from all other application layers.
- `domain` contains JSON-native models and validation without I/O.
- `application` coordinates use cases without knowing about files or Zigbee.
- `ports` define runtime infrastructure contracts.
- `adapters` implement persistence, memory test doubles, the UART frame codec,
  and a simulator for application tests.

The deleted `ZigbeeGateway` adapter was intentionally removed because it used a
planned `zcl_command` protocol that did not match the hardware-proven H2
coordinator. The next hardware gateway should be built from the experiment.

## Behavioral Contracts

### Time

- All timestamps supplied to `Planner` are UTC tuples:
  `(year, month, day, hour, minute)`.
- A `fixed_time` trigger represents local civil time and is converted through
  an explicit UTC-offset resolver.
- Israeli DST rules are currently supported from 2013 onward.
- Nonexistent local times during the DST spring transition are rejected.
- A repeated local hour during the autumn transition resolves to its first
  occurrence.
- An annual February 29 recurrence runs only in leap years.
- Each generated event keeps its recurrence `source_date`, including when an
  offset moves execution across midnight.

### Execution and Recovery

- Every event has a deterministic `event_id`.
- `Executor` retries only up to `max_attempts`.
- Only an execution-success gateway status is recorded as executed.
- A previously journaled event is not sent again after reboot.
- If an ACK is received but journal persistence fails, the result is
  `ack_unjournaled`; the command is not immediately retried.
- Catch-up windows are bounded to prevent unsafe replay after a badly
  configured clock.
- Journal size is configurable and must cover the chosen recovery horizon.

The remaining exactly-once risk is power loss after the H2 performs a command
but before the S3 records the ACK. The final H2 protocol must therefore make
`event_id` idempotent on the H2 as well.

### Persistence

- Entities are validated before storage.
- Writes go to a temporary file before replacing the active file.
- The previous active file is retained as a backup.
- Startup can recover from a readable temporary file or backup.
- The event journal uses an append-only log with bounded in-memory lookup and
  periodic atomic compaction.
- Corrupt data is reported explicitly and is never silently replaced with an
  empty collection.
- `fsync` and filesystem sync are used when exposed by the runtime.

## Supported Scheduling Model

Triggers:

- Fixed local time.
- A calculated zman.
- A calculated zman with a minute offset.

Recurrences:

- Daily or selected weekdays.
- Shabbat/Yom Tov and their eve.
- Chol Hamoed and Rosh Chodesh.
- Hebrew day, Hebrew date, Gregorian annual date, or one-time date.

Actions:

- `on`, `off`, and `toggle`.

Scheduled events reject `toggle`; manual control may still use it.

## Hardware Direction

Current pilot direction:

```text
CrowPanel Advance 7 inch ESP32-S3
    - UI, application logic, storage, and RTC access
    - UART connection to ESP32-H2

ESP32-H2
    - Zigbee coordinator and device gateway

Local Zigbee mesh
    - Wall switches, shutter controllers, and suitable DIN modules
```

Likely pilot devices include Sonoff Zigbee MINI modules and selected DIN-rail
controllers. Devices with a neutral wire commonly act as mesh routers, while
no-neutral devices commonly do not. Exact compatibility, electrical ratings,
router behavior, and certifications must be verified against the purchased
hardware and current vendor documentation.

All mains-voltage installation and load selection must be performed or approved
by a qualified electrician. Local files under `data-sheets/` are engineering
references, not a substitute for current vendor documentation or electrical
approval.

## Verification

Run locally in PowerShell:

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -v
python -m compileall -q src tests
```

When `setuptools` is available, the package can also be installed locally:

```powershell
python -m pip install -e .
```

## Next Steps

1. In `experiments/zigbee_probe`, replace the single `s_peer_short` with a
   small device table.
2. Persist and restore the device table so reset does not lose discovered
   devices.
3. Update the S3 probe to command a selected `short_addr` explicitly.
4. Verify two joined devices independently on hardware.
5. Promote the proven protocol into a new product hardware gateway.
6. Add H2-side idempotency using product `event_id`.
7. Revisit the web endpoint model once hardware discovery reports stable device
   identifiers.
