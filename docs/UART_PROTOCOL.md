# S3 ↔ H2 UART Protocol

The link between the hub (CrowPanel S3, or the AtomS3 in product B) and the
Zigbee coordinator (ESP32-H2, or NanoC6 in product B).

Implemented by `src/smart_kosher/adapters/uart_codec.py` and
`zigbee_gateway.py` on the hub side, and by
`firmware/h2_coordinator/main/{protocol,link,zb}.c`
on the coordinator side.

Wiring, per target: H2 (CrowPanel slot) S3 GPIO5 → H2 GPIO2, H2 GPIO24 →
S3 GPIO19. C6 (NanoC6 Grove) AtomS3 G2 → GPIO2, GPIO1 → AtomS3 G1. Both
UART1, 115200 8N1, no flow control.

## Envelope

```
<crc32hex> <json>\n
```

* `crc32hex` — eight **lowercase** hex digits, standard reflected CRC-32
  (identical to Python's `binascii.crc32`), computed over the JSON body only.
  Pinned on both sides by `host_test/test_main.c`.
* One space separator, then the compact JSON body, then `\n`.
* Lines longer than `PROTO_MAX_LINE` (**1024** bytes) are discarded **whole**,
  up to the next newline. It was 512 until a `ping` ack — capabilities plus
  eleven health counters, ~520 bytes — started being truncated into invalid
  JSON that still carried a valid CRC. A sender never truncates: an oversized
  frame is dropped and counted (`tx_oversize`) instead.

A receiver that cannot parse the prefix answers `bad_frame`; one whose checksum
disagrees answers `bad_crc`. Both are answered rather than dropped, so a sender
fails fast instead of waiting out its timeout.

## Message shapes

Every message carries `version: 1`.

| type | direction | fields |
|---|---|---|
| `command` | hub → coordinator | `op`, `request_id`, optional `payload` |
| `ack` | coordinator → hub | `op`, `status`, `request_id`, optional `payload` |
| `event` | coordinator → hub | `op`, optional `payload` |
| `error` | coordinator → hub | optional `request_id`, `payload.code`, `payload.message` |

`request_id` is the only correlation id; the coordinator echoes it verbatim.

## The ACK ladder

`status` on an `ack` says **how far the command actually got**. This is the
heart of the protocol: collapsing these into one "ok" is what let a schedule
that never reached a relay be recorded as executed.

| rung | meaning | hub maps to | journalable |
|---|---|---|---|
| `accepted` | parsed, and a request slot was taken | `accepted_by_h2` | no |
| `delivered` | the device's own radio confirmed the frame (AF/APS data confirm) | `confirmed_by_device` | **yes** |
| `failed` | the coordinator or the radio rejected it; `payload.aps_status` carries the raw code | `error` | no |
| `ok` | legacy: "the stack took it". Only sent by firmware < 0.8.0 | `sent_to_zigbee` (see below) | yes |
| `pong` | `ping` only | — | — |

The hub keeps `ok → sent_to_zigbee` for a coordinator that does **not**
advertise `delivery_ack`, so product B's existing firmware is unaffected. For
one that does, a bare `ok` means "taken but unproven" and maps to
`accepted_by_h2`, which is deliberately outside
`EXECUTION_SUCCESS_STATUSES` — the Executor retries it and a schedule stays
eligible for catch-up rather than being written off as done.

A command that is never confirmed is answered `failed` by the coordinator's own
expiry sweep, well inside the hub's 1500 ms ack timeout.

## Commands

| op | payload | ack |
|---|---|---|
| `ping` | — | `pong` + firmware, target, `network_up`, `capabilities`, `health` |
| `permit_join` | `duration` (clamped to 0–254) | `ok` + `duration` |
| `on_off` | `state` (`on`/`off`), `short_addr`, `endpoint` | `delivered` / `failed` |
| `read_attr` | `short_addr`, `endpoint` | `delivered` + `on_off`, or `failed` |
| `enable_reporting` | `short_addr`, `endpoint`, optional `cluster` (OnOff only) | `accepted` + `short_addr`, `endpoint`, `cluster`; outcome follows as an event |
| `read_report_cfg` | `short_addr`, `endpoint` | `delivered` + `zcl_status`, `min_interval`, `max_interval` |
| `remove_device` | `ieee_addr`, `short_addr` | `ok` |

`read_report_cfg` is diagnostic, not part of the control path: it asks a device
what reporting interval it is **actually** running. It exists because we ask
every device for `min_interval: 0` and one relay reported every ~3 s anyway —
devices clamp to their own minimum, and nothing else could tell that from a
broken configuration. (The measured answer: both relays return
`min_interval: 0, max_interval: 3600`, so the 3 s is that unit's own internal
behaviour, not a clamp.)

Error codes: `missing_payload`, `missing_state`, `missing_ieee`, `bad_addr`,
`bad_ieee`, `unknown_device`, `unknown_op`, `bad_json`, `bad_crc`, `bad_frame`,
`frame_too_long`, `no_network`, `send_failed`, `bind_failed`, `busy`.

The `missing_` codes mean the field was not there at all; the `bad_` codes mean
it was there and would not parse. Different faults with different fixes -- a
caller that never sent the field versus one that sent it wrong -- so
`missing_ieee` and `bad_ieee` stay separate, exactly as the firmware emits them
two lines apart. `tests/test_protocol_vocab_is_in_sync.py` holds this list and
the firmware to full equality, in both directions.

`busy` means the in-flight request table is full — honest backpressure, not a
dropped request.

## Events

| op | payload | notes |
|---|---|---|
| `boot` | firmware, version, target, uart pins, `capabilities` | repeated at startup; the hub may still be booting |
| `network_formed` | `channel`, `pan_id`, optional `note` | |
| `network_down` | — | the mesh is no longer usable; clears the hub's `network_up` |
| `formation_failed` | — | |
| `device_joined` | `ieee_addr`, `short_addr`, `endpoint` | `endpoint` is always 1; see `device_endpoints` |
| `device_endpoints` | `short_addr`, `endpoints` (array) | follows a join once ZDO discovery completes; this is what a multi-gang switch needs |
| `device_clusters` | `short_addr`, `endpoint`, `device_id`, `in_clusters`, `out_clusters` | one per endpoint, chained after `device_endpoints`. What each endpoint can actually do, from the device itself — this is how a two-gang switch's second endpoint is known to speak OnOff |
| `device_left` | `ieee_addr`, `short_addr`, `rejoin` | `rejoin: true` means it is coming straight back — the hub marks it unreachable rather than forgetting it |
| `attribute_report` | `short_addr`, `endpoint`, `on_off` | unsolicited; a physical switch press |
| `reporting_configured` | `short_addr`, `endpoint`, `cluster`, `status` | **check `status`** — its arrival is not success. **Check `cluster` too**: a verdict about any other cluster must not be read as a verdict about OnOff |
| `reporting_failed` | `short_addr`, `endpoint`, `cluster`, `reason`, optional `detail` | the hub retries with backoff — but only for OnOff. Reasons: `bind_failed`, `bind_no_response`, `configure_send_failed`, `configure_not_delivered`, `configure_no_response`, `configure_refused`, `unsupported_cluster`, `busy` |
| `permit_join_status` | `duration` | |

The two `_no_response` reasons are the coordinator's own expiry sweep speaking,
not the device: `bind_no_response` means the bind was sent and never answered,
`configure_no_response` the same one step later. Neither used to be emitted for
the bind stage at all, so a bind that vanished left the hub waiting on a verdict
that was never coming, against the promise two tables up that the outcome
follows as an event.

`cluster` on the two reporting events is load-bearing. Reporting means one
specific thing to the hub — "this device will tell us when its own wall switch
is pressed" — and only OnOff answers that. Before the field existed, a failed
metering configure flipped a perfectly healthy device to `reporting: false` and
started retrying it. OnOff is now the only configurable cluster (see below), so
the hub cannot cause that itself — but the guard stays on both sides, because a
coordinator on older firmware can still be mid-flight with a metering
configure.

## Capabilities

Advertised in `boot` and `ping` as `payload.capabilities`. Absent means an
older firmware, and the hub keeps the older, looser semantics.

| capability | meaning |
|---|---|
| `delivery_ack` | acks distinguish `delivered` from `accepted`; enables the journal rule above |
| `endpoint_discovery` | emits `device_endpoints` after a join |
| `cluster_discovery` | emits `device_clusters` per endpoint |
| `device_left` | emits `device_left` |
| `health_counters` | `ping` carries `payload.health` |

## Health counters

In `ping`'s payload under `health`. There is no other way to tell a saturated
link from a quiet one in the field.

All thirteen: `uptime_s`, `rx_frames`, `crc_errors`, `prefix_errors`,
`rx_line_drops`, `rx_queue_drops`, `rx_oversize`, `tx_queue_drops`,
`tx_oversize`, `tx_peak`, `txn_timeouts`, `txn_full`, `txn_peak`.

A loose H2 in its slot presents as a *selective* device fault — some commands
work, others fail with `bind_failed`. Check that `txn_timeouts` is zero before
blaming a device.

## Electrical measurement was removed (0.12.0)

Firmware 0.11.x carried a measurement path — per-cluster `enable_reporting`,
value decoding, and a `measurement_report` event — and it never worked: both
measurement clusters answered `configure_send_failed`, two hypotheses were
tried, neither fixed it. It was **removed** in 0.12.0 rather than debugged
further (product decision, 2026-08-05).

`measurement_report` therefore no longer exists, `enable_reporting` accepts
only OnOff (any other cluster fails with `unsupported_cluster`), and the
coordinator's own endpoint declares only what it does. A hub receiving a
`measurement_report` from a coordinator still on 0.11.x ignores it.

Cluster **discovery** stays. It is not part of measuring — it is how the hub
learns that a two-gang switch speaks OnOff on endpoint 2.

One thing this buys for free: reporting is now only ever configured for OnOff,
so a device can never have two configure transactions open at once. Matching
their responses was ambiguous (the coordinator matches the oldest open
configure for that address, and a Configure Reporting Response carries no
cluster), which could report a metering failure as an OnOff failure. That is
now impossible by construction rather than by care.

## Joining is hub-initiated

The coordinator never opens the network by itself. Firmware before 0.8.0 called
`open_network(180)` on every reboot, which left a customer's mesh accepting
joins for three minutes after any power cut. Only `permit_join` opens it.
