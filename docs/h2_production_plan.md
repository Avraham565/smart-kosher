# H2 Coordinator — Production Readiness Plan

Date opened: 2026-08-03

Scope: `firmware/h2_coordinator` (the coordinator
firmware) and the two things that consume it — `zigbee_gateway.py` and the
panel's reader task.

## Root causes (everything below is a consequence of these two)

1. **Optimistic reporting at the wrong layer.** Every asynchronous outcome is
   acked from the *local call site* rather than from the *actual outcome*. The
   ZCL Default Response — the real proof of delivery — is received and dropped
   at DEBUG (`main.c:177-179`). Consequence: `on_off` always acks `ok`, the
   Executor journals the event as executed, and the scheduler's dedup then
   refuses to retry a command that never reached the relay.
2. **Correlation by "last thing I sent" instead of by identity.**
   `s_pending_rid/short` and `s_bind_pending_short/ep` are single global slots
   written from the UART task and read from the Zigbee task, with no lock, no
   timeout, and no use of the TSN that ZCL provides (or of the `user_ctx` the
   bind API offers). Two devices pairing in one `permit_join` window is enough
   to lose one silently.

## Workstreams

Ordered by dependency. W0 and W1 need no hardware; W2+ need a build, and
flashing needs the H2 on USB (COM6).

### W0 — Ground truth from the SDK headers (blocks all firmware work)

- [x] **0.1** Baseline build of the unchanged firmware. **Done 2026-08-03**,
      exit 0 on WSL / ESP-IDF v5.3, output to `C:\tmp\h2_baseline_check`.
      Note for future runs: the script's default `-FlashOut` is
      `C:\tmp\h2_coordinator_flash`, which holds the *currently flashed*
      binaries — always pass an explicit path unless you mean to replace them.
- [x] **0.2** Headers read from
      `managed_components/espressif__esp-zigbee-lib/include`. Findings below.
- [x] **0.3** Resolve the stale header comment (`main.c:19-24` claims the report
      struct names are unconfirmed; `main.c:183-185` says they were confirmed).

#### Ground truth (recorded 2026-08-03, esp-zigbee-lib v2.x / IDF 5.3)

| Question | Answer |
|---|---|
| `ezb_zcl_on_off_{on,off}_cmd_req` return | **`ezb_err_t`** (`cluster/on_off.h:68,76`). `ezb_zcl_read_attr_cmd_req` likewise. The value discarded at `main.c:371-372` is meaningful — §2 is a confirmed defect, not a suspicion. |
| Per-command delivery confirmation | **Yes, and unused.** `ezb_zcl_cmd_ctrl_t` carries `cnf_ctx` (`zcl/zcl_common.h:56`) = `{cb, user_ctx}`. The callback receives `ezb_af_user_cnf_t` (`af.h:209-218`) with **`status`, `tsn`, `dst_addr`, `src_ep`, `dst_ep`, `cluster_id`** — APS-level delivery, correlated by *our own* context pointer. `cmd_on_off` leaves it zeroed. |
| ZCL Default Response contents | `in.header` is an `ezb_zcl_cmd_hdr_t*` with `src_addr`, `src_ep`, **`tsn`**, `cmd_id`, plus `in.status_code` and `in.rsp_to_cmd` (`zcl/zcl_general_cmd.h:448-459`). `main.c:177-179` logs only `status_code`, at DEBUG, and drops the header. |
| Is the default response even requested? | Yes — `fc.dis_default_rsp` defaults to 0 in the zero-initialised `cmd_ctrl`, so devices do answer. |
| Run work in stack context | `esp_zb_scheduler_alarm(cb, param, ms)` and `esp_zb_scheduler_user_alarm(cb, void *param, ms)` exist (`compat/esp_zigbee_core.h:59-61`). |
| Is `esp_zigbee_lock` recursive? | Not documented as such — `bool esp_zigbee_lock_acquire(TickType_t)` (`esp_zigbee.h:184`). Taking it inside a stack callback (`main.c:464`) stays a real risk; the scheduler alarms remove the need entirely. |
| ZDO endpoint discovery | `esp_zb_zdo_active_ep_req` / `esp_zb_zdo_simple_desc_req` with callbacks **and `user_ctx`** (`compat/zdo/esp_zigbee_zdo_command.h:158-178,298`). Multi-gang is reachable. |

**Design consequence — W3 and W4 get simpler and merge.** The original plan was
to hand-roll a TSN-matching transaction table. `cnf_ctx` is better: it hands the
delivery outcome back with *our own pointer*, so a txn slot needs no matching
heuristic at all, and `read_attr` / bind can use the same mechanism instead of
the four globals. There are then **two independent delivery proofs** available
and currently unused — the APS confirm (`cnf_ctx`) and the ZCL Default Response.
Build `delivered` on the APS confirm; treat the Default Response as the
higher-level corroboration.

### W1 — Consumer-side fixes (fully testable on CPython today, no hardware)

- [x] **1.1** `reporting_configured` now honours `payload["status"]`. Added the
      failing-status test the suite was missing (the old one only fed `"ok"`, so
      the bug was invisible).
- [x] **1.2** `reporting_failed` handled; both outcomes funnel through
      `_on_reporting_result`.
- [x] **1.3** Retry with capped exponential backoff, driven from `watchdog()`
      (no second task — an unreferenced task is GC'd on MicroPython). Deliberately
      **never gives up**: a switch that cannot report its own presses is a broken
      product, and one frame per 10 min costs nothing. `reporting_error` is
      surfaced in `zigbee.devices()` so the failure is diagnosable.
- [x] **1.4** Panel UART1 `rxbuf` 1024 → 4096 (`_ZIGBEE_RXBUF`).
- [x] **1.5** A `status: "delivered"` ack now maps to `confirmed_by_device`;
      `"ok"` keeps mapping to `sent_to_zigbee`. Old firmware is unaffected, so
      W4 needs no lockstep flash.

**Not changed on purpose:** the `"ok"` → `sent_to_zigbee` mapping stays until
W4 lands. `sent_to_zigbee` is in `EXECUTION_SUCCESS_STATUSES`, so flipping it to
the honest `accepted_by_h2` today would stop *every* schedule from ever being
journaled and retry them forever. The contract in `ports/device_gateway.py` is
already right — only the mapping is wrong, and it can only be fixed once the
firmware can actually say `delivered`.

### Firmware structure after W2–W6

Split so the parts worth testing can be tested off-device:

| file | contents | dependencies |
|---|---|---|
| `main/protocol.c/.h` | CRC-32, frame validation, line assembler | pure C |
| `main/txn.c/.h` | in-flight request table (generational handles) | pure C |
| `main/link.c/.h` | UART tasks + bounded queues + counters | ESP, no Zigbee |
| `main/zb.c/.h` | radio stack, commands, events, discovery | ESP + Zigbee |
| `main/main.c` | NVS, link start, boot beacon, task creation | thin |
| `host_test/` | `run.sh` — plain gcc, no framework | — |

Two invariants the split enforces, both broken by the old single file, and both
checkable with a grep:

* **Exactly one place takes the Zigbee lock** — `zb_dispatch_task`, with a
  bounded 200 ms timeout, never `portMAX_DELAY`, and never from a stack
  callback.
* **Exactly one task writes the UART** — `link.c`'s TX task. No stack callback
  ever touches the wire.

**Correction to the W0.2 plan.** The intent was zero locks, by running link
work inside the stack's own context via `esp_zb_scheduler_alarm`. That function
turns out to live behind `#if CONFIG_ZB_SDK_1xx` in `compat/esp_zigbee_core.h`
— it is legacy-SDK-only and **not available** on the 2.x native `ezb_*` API this
firmware uses. A lock is therefore unavoidable; what was avoidable was the harm
it did. The UART reader no longer blocks on it (it only enqueues), so a slow
radio can no longer cost a single received byte, which was the actual defect.
The transaction table gets its own recursive mutex rather than relying on an
undocumented assumption about which lock the stack holds while calling back.

### W2 — Firmware plumbing: no behaviour change, independently verifiable

- [x] **2.0** **Security: stop opening the network on every boot.**
      `main.c:242` calls `ezb_bdb_open_network(180)` unconditionally when the
      network is restored from NVS — so the mesh accepts joins for 3 minutes
      after every power cycle, unprompted, in a customer's home. Joining must be
      panel-initiated only. Also make `install_code_policy = false`
      (`main.c:639`) a recorded decision rather than a default.
- [x] **2.1** Single UART writer: outbound frames go on a queue drained by a
      dedicated TX task. Delete `s_uart_mutex`. No Zigbee callback ever touches
      the wire.
- [x] **2.2** RX task never calls the stack: parse to a `cmd_t`, push to a queue,
      drain it from *inside* the stack's own context. Delete every
      `esp_zigbee_lock_acquire` (`main.c:336,370,416,464,513,551`).
- [x] **2.3** Bounded queues; overflow increments a counter instead of corrupting
      or blocking.
- [x] **2.4** Health counters in the `ping` payload: `rx_frames`, `crc_errors`,
      `parse_errors`, `rx_overflows`, `tx_queue_high_water`, `txn_timeouts`,
      `txn_table_full`, `uptime_s`. Without these, field diagnosis is guesswork.
- [x] **2.5** Non-zero TX ring buffer; size RX for the worst-case burst.
- [x] **2.6** Small robustness: discard-until-newline on line overflow
      (`main.c:625-627` currently keeps appending the tail of the overlong line);
      emit an error frame on a malformed prefix instead of returning silently
      (`main.c:575-577`); clamp `permit_join` duration instead of truncating to
      `uint8_t` (`main.c:334`, 300 becomes 44).

### W3 — Transaction table (kills the correlation class of bugs)

- [x] **3.1** Fixed-size txn table owned solely by the Zigbee context, keyed by
      TSN + source address. Replaces all four globals.
- [x] **3.2** `read_attr` resolves by the responder's own identity (the
      `attribute_report` handler at `main.c:194-196` already does this correctly —
      apply the same pattern), and expires with a `timeout` ack instead of
      leaving a dangling rid forever.
- [x] **3.3** Bind / configure-reporting carry the slot through `user_ctx`
      (`main.c:505` passes NULL today).
- [ ] **3.4** Verify the device's **Configure Reporting Response** before
      declaring reporting active. **Marked done in error — what shipped in
      `config_report_confirm_cb` checks the APS *delivery* confirm of the
      configure command, i.e. "the request reached the device", not "the device
      accepted these values".** The distinction is the same one this whole plan
      exists to fix, and it bit here too.

      It matters concretely: hardware measurement on 2026-08-04 showed reports
      arriving a consistent ~3.0 s after a change, though we ask for
      `min_interval = 0`. Devices commonly clamp the interval to their own
      minimum and say so in the response we discard. Both SDK pieces exist:
      `EZB_ZCL_CORE_CONFIG_REPORT_RSP_CB_ID` for the response, and
      `ezb_zcl_read_report_config_cmd_req()` to ask a device what configuration
      it is actually running. Add a `read_report_cfg` op alongside, so the
      answer is a measurement rather than an inference.
- [x] **3.5** Table full → immediate `busy` error: natural backpressure instead
      of a silent overwrite.

### W4 — Real ACK ladder (protocol change; needs both sides)

- [x] **4.1** Replace the single `"ok"` with `accepted` → `sent` → `delivered`
      → `failed`. (`confirmed` already exists one level up, in `wait_for_report`.)
- [x] **4.2** Derive `delivered` from the ZCL Default Response.
- [x] **4.3** Version / capability negotiation at boot. Every frame already
      carries `"version": 1` and nobody checks it. Replaces the 10x blind boot
      beacon with a real handshake.
- [x] **4.4** **Executor journals only on `delivered`/`confirmed`.** This is the
      change that makes "the schedule ran" a fact instead of an assumption, and
      lets catch-up retry what genuinely never arrived.
- [x] **4.5** Write `docs/UART_PROTOCOL.md` — `uart_codec.py:1` already cites it
      and it does not exist.

### W5 — Device lifecycle

- [x] **5.1** Handle `LEAVE_INDICATION` → `device_left` event; the panel's
      registry currently keeps a departed device forever.
- [x] **5.2** `s_net_up` must return to false (`main.c:65` is never cleared, so
      `ping` keeps reporting `network_up: true` after the network is gone and the
      panel footer lies).
- [x] **5.3** ZDO `Active_EP_req` + `Simple_Desc_req` on join; report the real
      endpoint list instead of the hardcoded `1` (`main.c:289`). This is what
      unblocks multi-gang switches.

### W6 — Tests and docs

- [x] **6.1** Split the pure layers (frame codec, dispatch, txn table — no ESP
      dependencies) into a host-buildable unit with tests. The firmware has zero
      tests today; every verification is flash-and-squint. The Python side
      already does this right (`uart_codec` is pure and tested).
- [x] **6.2** Fix the dangling doc reference in `uart_codec.py:1`.
- [ ] **6.3** Hardware verification matrix: two devices pairing in one window;
      command to a powered-off device; device that left; coordinator reboot mid-
      command; multi-gang endpoint discovery.
- [ ] **6.4** **Find the real `max_children` ceiling.** `CONFIG_COORD_MAX_CHILDREN`
      is 10 — inherited from Espressif's coordinator example, never derived. It
      caps *direct* children, not the network (mains switches route), but in a
      home where every switch is in range of the panel they all try the
      coordinator first, and an 11th then depends on some router adopting it.
      The field is a `uint8_t` so the API allows far more; the true limit is the
      stack's internal neighbour table, which this SDK exposes through no
      Kconfig option. So it can only be found by trying: raise it, confirm the
      network still forms, and confirm 11+ devices join directly. Left at the
      proven value until there is hardware to try it on.

## Removed: electrical measurement (0.12.0, 2026-08-05)

0.10.0 added cluster discovery and 0.11.x built measurement reporting on top of
it. Measurement never worked — both clusters answered `configure_send_failed`,
two hypotheses were tried and neither fixed it — and rather than a third round
of guessing it was **removed** as a product decision: a missed reading costs a
number, and the effort is better spent where a miss costs a Shabbat.

Gone: the reportable-attribute table's measurement rows, ZCL value decoding,
the `measurement_report` event, the metering cluster descriptors on the
coordinator's own endpoint, and everything downstream of them in
`zigbee_gateway.py`.

Kept: **cluster discovery**. It answers "what can this endpoint do", which is
what multi-gang support needs, and it is independent of measuring anything.

Closes W3.4's remaining ambiguity for free. With OnOff the only configurable
cluster, a device can never have two configure transactions open at once — so
the `on_config_report_rsp` matching (oldest open configure for that address,
because a Configure Reporting Response carries no cluster) can no longer
mis-attribute a metering failure to OnOff. If measurement is ever revived, that
correlation must be fixed first — by TSN, which `config_report_confirm_cb` does
not currently record.

## What we are deliberately keeping

The CRC32+JSON line envelope (proven, terminal-debuggable — not switching to
binary); the stateless-H2 / panel-owns-the-registry split; the ping-verdict-only
circuit breaker; ieee-keyed registry healing; `wait_for_report` observed-state
confirmation. These are good decisions.
