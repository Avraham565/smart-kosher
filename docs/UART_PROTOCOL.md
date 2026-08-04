# S3 ↔ H2 UART Protocol

The link between the hub (CrowPanel S3, or the AtomS3 in product B) and the
Zigbee coordinator (ESP32-H2, or NanoC6 in product B).

Implemented by `src/smart_kosher/adapters/uart_codec.py` and
`zigbee_gateway.py` on the hub side, and by
`experiments/zigbee_probe/h2_coordinator_firmware/main/{protocol,link,zb}.c`
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
* Lines longer than 512 bytes are discarded **whole**, up to the next newline.

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
| `enable_reporting` | `short_addr`, `endpoint` | `accepted`; outcome follows as an event |
| `remove_device` | `ieee_addr`, `short_addr` | `ok` |

Error codes: `missing_payload`, `missing_state`, `bad_addr`, `bad_ieee`,
`unknown_device`, `unknown_op`, `bad_json`, `bad_crc`, `bad_frame`,
`no_network`, `send_failed`, `bind_failed`, `busy`.

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
| `device_left` | `ieee_addr`, `short_addr`, `rejoin` | `rejoin: true` means it is coming straight back — the hub marks it unreachable rather than forgetting it |
| `attribute_report` | `short_addr`, `endpoint`, `on_off` | unsolicited; a physical switch press |
| `reporting_configured` | `short_addr`, `endpoint`, `status` | **check `status`** — its arrival is not success |
| `reporting_failed` | `short_addr`, `endpoint`, `reason`, optional `aps_status` | the hub retries with backoff |
| `permit_join_status` | `duration` | |

## Capabilities

Advertised in `boot` and `ping` as `payload.capabilities`. Absent means an
older firmware, and the hub keeps the older, looser semantics.

| capability | meaning |
|---|---|
| `delivery_ack` | acks distinguish `delivered` from `accepted`; enables the journal rule above |
| `endpoint_discovery` | emits `device_endpoints` after a join |
| `device_left` | emits `device_left` |
| `health_counters` | `ping` carries `payload.health` |

## Health counters

In `ping`'s payload under `health`. There is no other way to tell a saturated
link from a quiet one in the field.

`uptime_s`, `rx_frames`, `crc_errors`, `prefix_errors`, `rx_line_drops`,
`rx_queue_drops`, `tx_queue_drops`, `tx_peak`, `txn_timeouts`, `txn_full`,
`txn_peak`.

## Joining is hub-initiated

The coordinator never opens the network by itself. Firmware before 0.8.0 called
`open_network(180)` on every reboot, which left a customer's mesh accepting
joins for three minutes after any power cut. Only `permit_join` opens it.
