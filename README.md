# Smart Kosher

Smart Kosher is an offline-first home automation core for reliable civil-time
and Jewish-calendar scheduling. The intended product uses a local wall-mounted
controller, requires no cloud service or smartphone, and prepares device
behavior for Shabbat and Jewish holidays.

## The two products

| | Product A — the wall panel | Product B — headless hub |
|---|---|---|
| status | **active** | **paused** — code kept, not being worked on |
| hardware | CrowPanel Advance 7" (ESP32-S3) + ESP32-H2 | M5 AtomS3 Lite + M5 NanoC6 |
| runs | `products/panel/` — UI **and** brain in one MicroPython process | `products/hub/` — API only, no UI |
| client | itself (touchscreen) | `client/` — a Windows app over USB or LAN |
| schedules fire? | yes | **no — the engine is shared, but no task starts it** |

Both share one brain: `src/smart_kosher/`, imported on the device from `/lib`.

## Repository map

```text
src/smart_kosher/         the brain — hardware-independent, unit-tested
  zmanim/                 offline calendar and zmanim calculations
  domain/                 business models and validation rules
  application/            Planner, Executor, RecoveryService, Api dispatcher
  ports/                  Clock, Repository, Gateway, Journal contracts
  adapters/               JSON storage, RTC, UART codec, ZigbeeGateway
  web/                    HTTP channel (Microdot) over the Api
  data/                   packaged and validated city profiles

products/panel/           PRODUCT A: LVGL UI + brain + scheduler
  device/                 flashed to the CrowPanel — the deploy payload IS this
  hwtest/                 device-side test suites, uploaded per run
  host/                   deploy, launchers, clean_board — run on the PC
products/hub/             PRODUCT B (paused)
  device/                 flashed to the AtomS3: main.py, device_cleanup.py
  host/                   deploy.ps1, runs on the PC
client/                   Windows desktop client for product B (paused)

firmware/
  h2_coordinator/         ESP32-H2 / NanoC6 Zigbee coordinator (C, ESP-IDF)
  tools/                  build and flash scripts for it

tests/                    unit tests for the brain, gateway and scheduler
  data/                   committed reference values (zmanim golden table)
tools/zmanim_golden/      regenerates that table from KosherJava (needs a JDK)
tools/zigbee_probe/       exploratory MicroPython probes (not shipped)
docs/                     protocol, hardware audit, H2 production plan
data-sheets/              local device notes and vendor references
```

`src` is a source directory, not an import namespace:

```python
from smart_kosher.application.planner import Planner, PlannerConfig
from smart_kosher.data import get_city, load_cities
from smart_kosher.zmanim import compute_zmanim
```

## Architecture

The brain follows a lightweight Ports and Adapters structure:

```text
Repository -> Planner -> Event -> Executor -> DeviceGateway -> H2 -> Zigbee
                                      |
                                      v
                                EventJournal
```

- `zmanim` is independent from all other application layers.
- `domain` contains JSON-native models and validation without I/O.
- `application` coordinates use cases without knowing about files or Zigbee.
  `Api.dispatch(op, params)` is the single command surface; every channel
  (the panel UI in-process, HTTP, USB serial) is a thin adapter over it.
- `ports` define runtime infrastructure contracts.
- `adapters` implement persistence, the UART frame codec, the real
  `ZigbeeGateway`, and test doubles.

## Behavioral contracts

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
- Zmanim conform to **KosherJava 2.5.0**, the library this implementation was
  derived from. `tests/test_zmanim_reference.py` checks all 18 against that
  library's own committed output, agreeing to within a second. The normal run
  sweeps a fixed sample spanning every city, month and year, which keeps it
  under half a second. The exhaustive sweep of all 58,440 city-days (over a
  million comparisons, ~6 s) is opt-in:

  ```
  ZMANIM_FULL_REFERENCE=1 python -m pytest tests/test_zmanim_reference.py
  ```

  Run it when touching `src/smart_kosher/zmanim`, changing a city, or
  regenerating the table. Regenerate with `python tools/zmanim_golden/generate.py`
  (needs a JDK; nothing else in the project does).
- Candle lighting is a fixed product rule, identical everywhere in Israel and
  not a setting: `CANDLE_OFFSET_MINUTES` = 18 minutes before sunset, the
  reference library's own default. There is no UI for it and the API rejects a
  write; a `settings.json` written before this rule cannot override it, and
  reads report the constant rather than what is stored.
- Shabbat exit is an **angle, not an offset**: 8.5° below the horizon, which is
  what the reference library calls tzais. It was a flat 36 minutes once — the
  value that angle happens to take in Jerusalem at the equinox — which let
  Shabbat out roughly six minutes early in June.
- Elevation corrects the displayed `netz_hachama` and `shkia` and nothing else.
  Every derived zman — temporal hours, MGA, Rabbeinu Tam, candle lighting — is
  computed from sea level, matching the reference library, whose `useElevation`
  defaults to off. So above sea level the gap between candle lighting and the
  displayed `shkia` is larger than 18 minutes (about 23 in Jerusalem), and that
  is correct. City elevations are sampled from the SRTM 30 m model at each
  city's own coordinate.
- **40 packaged cities** span the country — Eilat and Mitzpe Ramon in the south,
  Nahariya and Kiryat Shmona in the north, sea level through 850 m — and the
  user picks the nearest. Choosing one applies its latitude, longitude *and*
  elevation together: `PUT /api/settings {"city": "tel_aviv"}` sets all three,
  because a name that moved without its coordinates is how a location silently
  goes wrong. Explicit coordinates in the same request win, so a locality the
  list does not cover can still be entered by hand. `tests/test_cities.py`
  checks the list as data — every coordinate inside Israel, no two entries the
  same place, and a coherent day computed at each.

### Execution and recovery

- Every event has a deterministic `event_id`.
- `Executor` retries only up to `max_attempts`.
- Only an execution-success gateway status is recorded as executed. Against a
  coordinator that can prove delivery, that means the device's own radio
  confirmed the frame — a command that never reached the relay is **not**
  journaled, and stays eligible for retry and catch-up.
- A previously journaled event is not sent again after reboot.
- If an ACK is received but journal persistence fails, the result is
  `ack_unjournaled`; the command is not immediately retried.
- Catch-up windows are bounded to prevent unsafe replay after a badly
  configured clock.
- Journal size is configurable and must cover the chosen recovery horizon.

The remaining exactly-once risk is power loss after the relay acts but before
the hub records the ACK.

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

## Supported scheduling model

Triggers: fixed local time; a calculated zman; a calculated zman with a minute
offset.

Recurrences: daily or selected weekdays; Shabbat/Yom Tov and their eve;
Chol Hamoed and Rosh Chodesh; Hebrew day, Hebrew date, Gregorian annual date,
or a one-time date.

Actions: `on`, `off`, and `toggle`. Scheduled events reject `toggle` — it is
not deterministic under replay and recovery; manual control may still use it.

## Known gaps

- **Product B never fires schedules.** `products/hub/device/main.py` composes the
  Executor and the Api but never starts a scheduler tick, so a saved schedule
  is stored and never executed there. The engine itself is no longer the
  obstacle — `application/scheduler.py` is in the shared brain and product B
  imports it already; what is missing is one task on its loop, and hardware to
  verify it on.
- **Multi-gang switches share one state.** The coordinator discovers a device's
  endpoint list and commands honour a per-entity `zigbee_endpoint`, but the
  gateway keys live state by ieee alone, so two gangs of one switch overwrite
  each other's reported state.
- **Electrical measurement was removed** (2026-08-05). It never worked in
  0.11.x, and 0.12.0 takes it out rather than debugging it further. See
  `docs/UART_PROTOCOL.md`. Cluster discovery stays — it is what multi-gang
  needs and has nothing to do with measuring.
- **No `reconcile` yet.** The rule is decided (self-inflicted drift gets
  corrected, human intervention is respected until the target's next scheduled
  transition) but nothing implements it; it needs per-command attribution,
  which does not exist.
- **`tset_hakohavim` and `tset_hakohavim_shabbat` compute the same instant.**
  Both are 8.5° below the horizon, so the panel lists two rows with one time.
  They are kept as separate keys deliberately: Shabbat exit is the product
  concept saved schedules point at, so adopting a stricter shiur later is a
  one-line change every schedule follows. The reference library has no Shabbat
  exit at all — only one tzais.
- **Groups and date-based recurrences have no UI** on the panel.

## Verification

```powershell
python -m pip install -e ".[dev]"   # pytest, ruff, pyserial
$env:PYTHONPATH = "src"
python -m pytest -q                 # brain, gateway, scheduler
python -m ruff check .              # lint; expected to be clean
```

Coordinator firmware, pure layers (protocol/txn), on the host:

```bash
bash firmware/h2_coordinator/host_test/run.sh
```

On real hardware, against the real H2 and real relays:

```powershell
python products/panel/host/run_hwtest.py
```

On real hardware, against the real display — builds each screen on the panel
and checks it fits 800×480, since anything that does not is drawn off the page
and lost silently (there is no scrolling to reach it):

```powershell
python products/panel/host/run_hwtest_ui.py
```

On real hardware, zmanim computed by the device diffed against the committed
reference table. The panel is a single-precision float build, where an offset
added to a Julian day can vanish entirely — the host suite cannot see that, so
this is the only check that covers the device's arithmetic:

```powershell
python products/panel/host/run_hwtest_zmanim.py
```

All three stop `main.py` for the run and restore it afterwards.

## Hardware direction

```text
CrowPanel Advance 7 inch ESP32-S3
    - UI, application logic, storage, RTC (PCF8563), scheduler
    - UART1 to ESP32-H2 (S3 GPIO5 -> H2 GPIO2, H2 GPIO24 -> S3 GPIO19)

ESP32-H2
    - Zigbee coordinator and device gateway

Local Zigbee mesh
    - Wall switches, shutter controllers, and suitable DIN modules
```

Pilot devices are Sonoff Zigbee MINI modules and selected DIN-rail
controllers. Devices with a neutral wire commonly act as mesh routers, while
no-neutral devices commonly do not. Exact compatibility, electrical ratings,
router behavior, and certifications must be verified against the purchased
hardware and current vendor documentation.

All mains-voltage installation and load selection must be performed or approved
by a qualified electrician. Local files under `data-sheets/` are engineering
references, not a substitute for current vendor documentation or electrical
approval.
