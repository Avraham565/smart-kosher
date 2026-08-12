# Repository restructure — plan

Written 2026-08-12, after the audit in `AUDIT-CONCLUSION.md`. Verified three
times; the passes are recorded at the end.

**The goal in one line:** every directory should answer "who runs this, and on
what hardware" without opening a file.

Today it does not. `panel_mp/` holds modules flashed to a board, scripts that
run on the developer's PC, and test fixtures uploaded per-session, all in one
flat list. Product B is called `deploy/atoms3/`, which reads like a deploy
script and is actually a product. The live coordinator firmware sits under
`experiments/`. `dev_server.py` floats at the root.

---

## Target tree

```
src/smart_kosher/          the shared brain — UNCHANGED, see "what does not move"
products/
  panel/                   Product A — CrowPanel S3 + H2
    device/                  flashed to the board (30 modules + fonts/)
    hwtest/                  device-side test fixtures, uploaded per session
    host/                    runs on the PC: deploy, launchers, clean_board
    README.md
  hub/                     Product B — AtomS3 Lite + NanoC6
    device/                  main.py, device_cleanup.py
    host/                    deploy.ps1
apps/
  desktop/                 SmartKosher.exe (was client/)
firmware/
  h2_coordinator/          live C firmware (was under experiments/)
  tools/                   build + flash scripts
tools/
  dev_server.py            (was at the repo root)
  zmanim_golden/
  zigbee_probe/            exploratory probe scripts only
tests/  docs/  data-sheets/
```

`experiments/` ceases to exist.

### The rule each directory obeys

| directory | rule |
|---|---|
| `products/*/device/` | **everything here is flashed, nothing else is.** deploy pushes the directory, not a list |
| `products/*/hwtest/` | device-side, uploaded only for a test run |
| `products/*/host/` | never touches the board's filesystem except through mpremote |
| `firmware/` | C, built with ESP-IDF |
| `tools/` | developer utilities, not shipped, not linted as production |

---

## Why the `device/` split is the load-bearing part

`panel_mp/deploy.ps1:38-44` hand-lists 29 module names, with this comment
beside it:

> `# uart_tap.py is imported unconditionally by main.py … so leaving it out of
> this list bricks the boot.`

That is a bug waiting on a rename, and it already fired once this week. When
`device/` is a directory, the deploy pushes its contents and the list stops
existing. **This alone justifies the move.** Everything else is tidiness.

Two ordering constraints survive and must be preserved explicitly:

1. `main.py` is copied **last**, after a reset to a DMA-free board
   (`deploy.ps1:22-29, 86-88`). Globbing must exclude it, then copy it.
2. `fonts/*.bin` go to the board root by basename (`deploy.ps1:31-35`), because
   `binfont_create` resolves `S:<name>`.

The board's filesystem is flat regardless of the repo layout — every module
lands at `:`. So `import store` on the device is unaffected by any of this.

---

## What does NOT move, and why

| kept | reason |
|---|---|
| `src/smart_kosher/` | `src/` is the Python packaging convention `pyproject.toml:20` is built on; every documented command says `PYTHONPATH=src`; it deploys to `/lib`. Renaming costs a lot and buys nothing |
| `tests/` | one host suite for the whole repo, `pyproject.toml:31` |
| `docs/`, `data-sheets/` | already correct |
| `AUDIT-CONCLUSION.md` paths | **deliberately stale.** It is a dated record of what was true on 2026-08-12, in the same spirit as `docs/hardware_audit.md:9-15`. Do not rewrite its paths; add a dated note at the top instead |

---

## Stages

One commit per stage. `git mv` throughout so history follows. The suite must be
green at the end of every stage; where a stage cannot be proven by tests, the
gate is written out explicitly.

### Stage 1 — `firmware/` out of `experiments/`

Lowest risk: self-contained C plus two PowerShell scripts.

```
git mv experiments/zigbee_probe/h2_coordinator_firmware firmware/h2_coordinator
git mv experiments/zigbee_probe/tools/build_h2_coordinator.ps1 firmware/tools/
git mv experiments/zigbee_probe/tools/flash_h2_coordinator.ps1 firmware/tools/
git mv experiments/zigbee_probe/tools tools/zigbee_probe       # probes that remain
git mv experiments/_archive/README.md docs/display-lineage.md
git rm experiments/zigbee_probe/.gitignore                      # replaced, see below
```

Then split `experiments/zigbee_probe/README.md`: the firmware/wiring half to
`firmware/h2_coordinator/README.md`, the probe half to
`tools/zigbee_probe/README.md`. It currently calls itself "Disposable" in line 3
and "the current source of truth" in lines 10-11 — the contradiction the audit
flagged. Splitting it resolves that by construction.

**Edits:**

| file | change |
|---|---|
| `pyproject.toml:36` | `extend-exclude = ["experiments"]` → `["tools/zigbee_probe"]` |
| `.gitignore:37-40` | delete — `h2_firmware/` has not existed for months |
| `.gitignore` | add `firmware/h2_coordinator/build/`, `.../sdkconfig`, `.../managed_components/` (from the deleted `experiments/zigbee_probe/.gitignore`; keep its note that `dependencies.lock` is deliberately tracked) |
| `firmware/tools/build_h2_coordinator.ps1:15-16` | `$experimentRoot` → `$firmwareRoot`; `Join-Path $firmwareRoot "h2_coordinator"`. The `Split-Path -Parent $PSScriptRoot` idiom still resolves correctly — only the names change |
| `docs/UART_PROTOCOL.md:7-9` | firmware path |
| `docs/hardware_audit.md` | add a dated note; do not rewrite history |
| `docs/h2_production_plan.md` | firmware paths |
| `CLAUDE.md` (commands section) | the `experiments/` paragraph |
| `README.md` | firmware paths |

**Gate:** `ruff check .` clean (proves the lint-exclude rename is right), and
`firmware/tools/build_h2_coordinator.ps1` runs to a successful build.

### Stage 2 — `products/hub/`

```
git mv deploy/atoms3/main.py           products/hub/device/main.py
git mv deploy/atoms3/device_cleanup.py products/hub/device/device_cleanup.py
git mv deploy/atoms3/deploy.ps1        products/hub/host/deploy.ps1
```

`device_cleanup.py` goes to `device/` because it executes on the board
(`mpremote run`), even though the host invokes it.

**Edits:**

| file | change |
|---|---|
| `pyproject.toml:52` | `"deploy/atoms3/main.py" = ["F841"]` → `"products/hub/device/main.py"` |
| `products/hub/host/deploy.ps1:23` | `$repoRoot = …"..\..")` → `"..\..\.."` (one level deeper) |
| `products/hub/host/deploy.ps1:67` | `$PSScriptRoot\device_cleanup.py` → `$PSScriptRoot\..\device\device_cleanup.py` |
| `products/hub/host/deploy.ps1:84` | `$PSScriptRoot\main.py` → `$PSScriptRoot\..\device\main.py` |
| `products/hub/host/deploy.ps1:4-6` | usage lines in the header comment |
| `README.md`, `CLAUDE.md` | product B path |

**Gate:** `ruff check .` clean; `deploy.ps1 -StageOnly` succeeds (it exercises
`$repoRoot` without needing a board); then a real deploy to the AtomS3.

### Stage 3 — `products/panel/{device,hwtest,host}`

The biggest win and the biggest risk. **30 files to `device/`:**

```
brain bridge city_picker clock dev_common device_page display hebdate keyboard
lvgl_loop main pages reactive room_page rooms_page sched_describe sched_labels
schedule_add schedules_page settime shell store text_input theme toast uart_tap
ui_home widgets zmanim_page zone_picker      (29 modules + main.py)
plus fonts/  (5 .bin)
```

**3 to `hwtest/`:** `hwtest.py`, `hwtest_ui.py`, `hwtest_zmanim.py`
**6 to `host/`:** `deploy.ps1`, `clean_board.py`, `run_common.py`,
`run_hwtest.py`, `run_hwtest_ui.py`, `run_hwtest_zmanim.py`
**1 stays at the product root:** `README.md`

**Edits:**

| file | line | change |
|---|---|---|
| `pyproject.toml` | 42 | `src = [".", "src", "panel_mp", "client"]` → `[".", "src", "products/panel/device", "products/panel/hwtest", "apps/desktop"]` |
| `host/deploy.ps1` | 15-17 | `$here` is now `host/`; add `$device = Join-Path $here "..\device"`; `$repoRoot` goes up **three** levels, not one |
| `host/deploy.ps1` | 27 | `clean_board.py` is a sibling in `host/` — unchanged |
| `host/deploy.ps1` | 32 | fonts from `$device\fonts\*.bin` |
| `host/deploy.ps1` | 38-52 | **replace the hand list with a glob** over `$device\*.py` excluding `main.py` |
| `host/deploy.ps1` | 87 | `main.py` from `$device` |
| `host/run_hwtest.py` | 20 | add `DEVICE = os.path.join(HERE, "..", "device")`, `HWTEST = …/"hwtest"` |
| `host/run_hwtest.py` | 44,50,59 | `clean_board.py` stays in `HERE`; `hwtest.py` from `HWTEST`; `main.py` from `DEVICE` |
| `host/run_hwtest_ui.py` | 22 | `PAYLOAD` names resolve against `DEVICE`, except `hwtest_ui.py` against `HWTEST` |
| `host/run_hwtest_ui.py` | 54-60 | `HERE/../src/...` → `HERE/../../../src/...` |
| `host/run_hwtest_zmanim.py` | 20 | `ROOT = dirname(HERE)` → three levels up |
| `tests/test_panel_scheduler.py` | 25 | sys.path → `products/panel/device` |
| `tests/test_zman_keys_are_in_sync.py` | 26-27 | `panel_mp/` → `products/panel/device/` |
| `CLAUDE.md`, `README.md`, product README | — | paths |

**Gate:** full suite green (it covers `test_panel_scheduler` and
`test_zman_keys_are_in_sync`, both of which resolve these paths), `ruff check .`
clean, **and a real flash to the CrowPanel plus `run_hwtest_ui.py` 26/26.** No
test catches a wrong deploy payload; only the board does.

### Stage 4 — `apps/desktop/`

```
git mv client apps/desktop
```

| file | line | change |
|---|---|---|
| `apps/desktop/app.py` | 21 | `_SRC = dirname(_HERE)/"src"` → up **two** levels |
| `apps/desktop/build.ps1` | 10 | `$repoRoot = …"..")` → `"..\.."` |
| `tests/test_route_table.py` | 32 | `ROOT / "client" / "bridge.py"` → `ROOT / "apps" / "desktop" / "bridge.py"` |
| `tests/test_route_table.py` | 13-17 | the docstring names `client/bridge.py` and `panel_mp/bridge.py` |
| `tests/test_zman_keys_are_in_sync.py` | 28 | `client/ui/js/labels.js` |
| `pyproject.toml` | 42 | already handled in stage 3 |

**Gate:** suite green; **rebuild the exe and run it** (`--no-window --port N`,
then `GET /bridge/status`). The exe is the only thing that proves `--paths` and
the frozen path setup still resolve.

### Stage 5 — `tools/dev_server.py`

```
git mv dev_server.py tools/dev_server.py
```

| file | line | change |
|---|---|---|
| `tools/dev_server.py` | 4 | usage line in the docstring |
| `tools/dev_server.py` | 14 | `dirname(__file__)/src` → up two levels |
| `tools/dev_server.py` | 36 | `dev_data/` now lands under `tools/`; `.gitignore:29` matches at any depth, so no change needed there |
| `README.md`, `CLAUDE.md` | — | the `python dev_server.py` command |

**Gate:** `python tools/dev_server.py` serves `http://localhost:5004/api/status`.

---

## Risk register

| risk | where | mitigation |
|---|---|---|
| **Wrong flash payload bricks the boot** | stage 3 | The glob removes the class of bug, but verify the first deploy against a board and read the boot log. `main.py` must still be copied last |
| Stale modules left on a board | stage 3 | `deploy.ps1:74-84` already removes named stale files. A renamed module is a *new* stale case — add any renamed name to that list, or wipe the board |
| `$repoRoot` off by a level | 2, 3, 4 | Each deploy script computes it from `$PSScriptRoot`. Every stage changes the depth. Print it once and eyeball |
| Frozen exe silently missing the core | stage 4 | Only a rebuilt exe proves it. Never accept "the tests pass" here |
| Two modules named `bridge` | stage 4 | `apps/desktop/bridge.py` and `products/panel/device/bridge.py` still collide by name. `tests/test_route_table.py` already loads by file path — keep it that way |
| History becomes hard to follow | all | `git mv` + one move per commit. `git log --follow <path>` still works |

---

## Order and why

1 → 2 → 5 are near-free and independent. 3 is the valuable one and should
follow 1–2 so the tree is already settled when the risky move lands. 4 last,
because it is the only one whose verification needs a build.

A reasonable smaller scope, if appetite runs out: **stages 1, 2 and 3 alone**
deliver almost all the clarity. 4 and 5 are cosmetic by comparison.

---

## Execution notes for a fresh session

- Read this file and `CLAUDE.md` first. `CLAUDE.md` is the invariants; this is
  the map.
- After every stage: `ruff check .` and `PYTHONPATH=src python -m pytest -q`
  (371 tests, 1,455 subtests as of `3ae1c01`).
- Before committing any stage, verify from the index rather than the working
  tree — the audit's own P0 finding was a file that existed locally and not in
  git, and this plan creates many new paths:
  ```
  git checkout-index -a --prefix=/tmp/check/ && cd /tmp/check &&     PYTHONPATH=src python -m pytest -q
  ```

### Prose references — a separate sweep, not part of any stage

20 files name these directories in **comments and docstrings only**, with zero
functional path use. They break nothing, so they are deliberately not in the
stage tables above — but left alone they become exactly the stale-comment drift
the audit spent its time on.

```
products/panel/device/  brain bridge display lvgl_loop main pages shell theme
                        ui_home widgets clean_board(host)
products/panel/hwtest/  hwtest hwtest_ui hwtest_zmanim
src/smart_kosher/       adapters/h2_simulator adapters/zigbee_gateway
                        application/scheduler
tests/                  test_zigbee_gateway
tools/zigbee_probe/     s3_ui_probe
apps/desktop/           README.md
```

Do this as **one final commit** after stage 5, driven by grep rather than by
this list, since the list will have aged.

### No single grep finds everything

The sweep command below misses `client/app.py`, `client/build.ps1`,
`pyrightconfig.json` and the firmware build script, because those reference
`src` or a bare relative path rather than a product directory name. Run both:

```
grep -rln "panel_mp\|deploy/atoms3\|experiments\|client/ui\|dev_server"   --include=*.py --include=*.ps1 --include=*.toml --include=*.json --include=*.md .
grep -rn "PSScriptRoot\|dirname(__file__)\|parents\[\|Join-Path"   --include=*.py --include=*.ps1 .
```

---

## Verification record

The plan was checked three times before being committed. Each pass found
something, which is the only reason to record them.

**Pass 1 — completeness.** Enumerated every file naming a moved directory: **38**,
not the 31 quoted in conversation (the earlier grep omitted bare `experiments`
and `dev_server`). Of those, 18 carry functional paths and are covered by the
stage tables; **20 are prose only** and were missing from the plan entirely —
they are now the sweep section above. Also established that no single grep
suffices, hence the two commands.

**Pass 2 — correctness.** Verified every line number cited. Two were wrong:
`.gitignore` `dev_data/` is line **29**, not 20; `build.ps1`'s `$repoRoot` is
line **10**, not 11. Both corrected above. All other citations
(`deploy.ps1:38-44`, `pyproject.toml:20/31/36/42/52`, `run_hwtest_ui.py:54-60`,
and the rest) confirmed against the files.

**Pass 3 — simulation.** Exported `3ae1c01` to a scratch tree, performed **every
move in stages 1-5**, applied the config and test edits, and ran the suite:

```
371 passed, 1 skipped, 1455 subtests passed
All checks passed!                            (ruff)
```

Also confirmed in the moved tree that `tools/dev_server.py` and
`apps/desktop/app.py` still resolve `src/`.

The simulation caught one bad edit in this plan: the `sys.path` insert in
`tests/test_panel_scheduler.py:23-26` spans four lines, so the string this plan
originally gave for it did not match. The stage-3 table now points at the
statement rather than a fragment.

**It also surfaced the plan's most important risk, which no amount of reading
would have found:** after the move, `run_hwtest_zmanim.py` and
`run_hwtest_ui.py` compute paths that no longer exist —

```
GOLDEN  -> products/panel/tests/data/zmanim_golden.csv.gz   (missing)
cities  -> products/panel/host/../src/...                    (missing)
```

— and **both scripts still exit cleanly**, because they return at "No panel
found" long before touching those paths. The breakage is invisible without a
board plugged in. Treat the stage-3 runner edits as unverifiable by CI: make
them by inspection, and confirm on the bench.
