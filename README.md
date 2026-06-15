# Smart Kosher

Smart Kosher is an offline-first home automation core designed for reliable
civil-time and Jewish-calendar scheduling. The intended product uses a physical
wall-mounted controller, requires no cloud service or smartphone, and can
prepare device behavior for Shabbat and Jewish holidays.

The repository currently contains a tested, hardware-independent software core.
It does not claim to control real Zigbee devices yet.

## Current Status

Implemented and tested:

- Offline Jewish calendar, holidays, Omer counting, weekly parasha, and 19
  halachic times.
- Deterministic event planning from fixed local times or calculated zmanim.
- Israeli daylight-saving-time resolution without an online service.
- Cross-midnight schedules and bounded catch-up after delayed execution.
- Validated domain models for schedules, actions, events, zones, endpoints,
  and groups.
- Idempotent execution with bounded retries, ACK handling, and an execution
  journal.
- Atomic-style JSON persistence with temporary files, backup, recovery, and
  defensive copies.
- In-memory adapters and a deterministic ESP32-H2 simulator for testing.

Not implemented or hardware-validated:

- Real RTC, UART, ESP32-H2, Zigbee, LVGL UI, watchdog, pairing, or deployment.
- H2-side idempotency and the final UART protocol.
- Real power-loss, RTC drift, mesh range, and device compatibility testing.

## Project Structure

```text
src/
`-- smart_kosher/
    |-- zmanim/            Offline calendar and zmanim calculations
    |-- domain/            Business models and validation rules
    |-- application/       Planner, Executor, and RecoveryService
    |-- ports/             Clock, Repository, Gateway, and Journal contracts
    |-- adapters/          JSON, memory, and H2 simulator implementations
    `-- data/              Packaged and validated city profiles

tests/                     Tests kept outside production code
data-sheets/               Local product notes and vendor reference documents
```

`src` is a source directory, not an import namespace:

```python
from smart_kosher.application.planner import Planner, PlannerConfig
from smart_kosher.data import get_city, load_cities
from smart_kosher.zmanim import compute_zmanim
```

## Architecture

The project follows a lightweight Ports and Adapters structure:

```text
Repository -> Planner -> Event -> Executor -> DeviceGateway
                                      |
                                      v
                                EventJournal
```

- `zmanim` is independent from all other application layers.
- `domain` contains JSON-native models and business validation without I/O.
- `application` coordinates use cases without knowing about files or Zigbee.
- `ports` define the interfaces required from runtime infrastructure.
- `adapters` implement persistence, journals, and simulated device delivery.

### Main Components

| Component | Responsibility |
|---|---|
| `Planner` | Converts schedules and UTC time windows into deterministic events |
| `Executor` | Sends events, retries bounded failures, and records successful ACKs |
| `RecoveryService` | Plans and executes missed events inside a bounded catch-up window |
| `JsonRepository` | Persists validated entities with backup and recovery |
| `JsonEventJournal` | Prevents replay of recorded events after reboot |
| `H2Simulator` | Produces controlled ACK, timeout, and error responses without hardware |

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
- Only an ACK is recorded as successfully executed.
- A previously journaled event is not sent again after reboot.
- If an ACK is received but journal persistence fails, the result is
  `ack_unjournaled`; the command is not immediately retried.
- Catch-up windows are bounded to prevent unsafe replay after a badly
  configured clock.
- Journal size is configurable and must cover the chosen recovery horizon.

The remaining exactly-once risk is power loss after the H2 performs a command
but before the S3 records the ACK. The final protocol must therefore make
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

## Planned Hardware

The current pilot direction, pending physical verification:

```text
CrowPanel Advance 7" ESP32-S3
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

The built-in CrowPanel RTC is the initial pilot choice. A DS3231 and LiPo remain
optional until RTC retention, drift, and power-loss behavior are measured.

All mains-voltage installation and load selection must be performed or approved
by a qualified electrician. Local files under `data-sheets/` are engineering
references, not a substitute for current vendor documentation or electrical
approval.

## Known Limitations

- Israeli DST law may change; offline rules must be reviewed when legislation
  changes.
- Domain schemas validate individual records but do not yet verify all
  cross-record references, such as whether every group member exists.
- Recovery policy is technically bounded but still needs product decisions
  about which old actions should be skipped.
- The append-only JSON journal still needs endurance testing on the final
  embedded filesystem.
- Packaging is defined in `pyproject.toml`; the current local Python
  installation lacks `setuptools.build_meta`, so tests run directly from
  `PYTHONPATH=src`.

## Verification

The current suite contains 43 automated tests covering:

- Calendar round trips, known zmanim, parasha, cities, and DST boundaries.
- Invalid dates, coordinates, actions, schedules, and entity schemas.
- Fixed local times, midnight crossing, zman offsets, and catch-up.
- Retry behavior, journal failures, reboot recovery, and replay prevention.
- Repository CRUD, revisions, isolation, backup, corruption, and recovery.

Additional long-running checks have covered:

- 73,414 Gregorian/Hebrew date round trips from 1900 through 2100.
- Daily zmanim invariants for 2024 through 2040.
- A full simulated year through Planner, RecoveryService, Executor, simulator,
  and journal.

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

1. Validate cross-entity references and endpoint capabilities.
2. Define scenes and composite actions independent of Zigbee.
3. Define a versioned UART protocol with checksum, request ID, and `event_id`.
4. Implement H2-side idempotency and a device-state machine.
5. Define product recovery policy for stale or missed events.
6. Run extended simulations with clock jumps, DST, timeouts, and power loss.
7. After hardware arrives, validate RTC retention, UART pinout, Zigbee pairing,
   mesh behavior, UI, watchdog, and deployment.
