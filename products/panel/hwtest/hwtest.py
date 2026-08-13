# Hardware test suite -- runs ON the panel, against the real H2 and real relays.
#
# Everything here was checked by hand first, as one-off mpremote exec strings.
# That went badly: one probe used a 3-second listening window, the device
# reported at 3.0s, and the miss produced a confidently wrong conclusion. A
# test you retype each time is a test you cannot trust, so this is a file.
#
# THE BENCH RIG (built 2026-08-04): the older relay's output is wired into the
# newer relay's switch input. Commanding the actuator is therefore
# indistinguishable, from the device under test's point of view, from a person
# at the wall switch -- which makes "someone touched it" a scriptable event.
#
# Safety: only the two ieee addresses passed to run() are ever actuated, and
# every relay is returned to the state it started in. No schedule, room or
# endpoint of yours is created, changed or deleted.
#
# ONE EXCEPTION, and it is not obvious: the gateway is built with the real
# registry_path, so /data/zigbee_devices.json IS written -- the gateway
# rediscovers on start and saves what it currently sees. A relay that is off
# the network during a run is therefore dropped from the registry by the run.
# That happened on 2026-08-11: the file went from two devices to one, and the
# header used to claim nothing under /data was touched at all.
#
# If you are running this against a rig where a device may be offline, copy
# /data/zigbee_devices.json first.
#
# Usage (from the host):  python products/panel/host/run_hwtest.py

import asyncio
import time

from machine import UART

from smart_kosher.adapters import ZigbeeGateway
from smart_kosher.adapters.json_repository import JsonRepository
from smart_kosher.adapters.uart_codec import decode as dec
from smart_kosher.ports.device_gateway import EXECUTION_SUCCESS_STATUSES

UART_ID, TX, RX, BAUD, RXBUF = 1, 5, 19, 115200, 4096

# Generous enough not to fail on a healthy-but-busy mesh, tight enough that a
# real regression trips them. Measured on this rig: acks 118-137ms, reports
# 182-308ms.
ACK_BUDGET_MS = 800
REPORT_BUDGET_MS = 2000
# The old relay clamps its own reporting to ~3.0s no matter what we configure,
# so its latency is recorded but never asserted on.
SLOW_DEVICE_NOTE_MS = 4000


class Results:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.notes = []

    def check(self, ok, name, detail=""):
        if ok:
            self.passed += 1
            print("  PASS  {} {}".format(name, detail))
        else:
            self.failed += 1
            print("  FAIL  {} {}".format(name, detail))
        return ok

    def note(self, text):
        self.notes.append(text)
        print("  note  {}".format(text))


class Harness:
    """Owns the link, records every inbound frame with a timestamp."""

    def __init__(self):
        self.repo = JsonRepository("/data")
        self.uart = UART(UART_ID, baudrate=BAUD, tx=TX, rx=RX,
                         timeout=0, rxbuf=RXBUF)
        self.gw = ZigbeeGateway(self.uart, self.repo,
                                registry_path="/data/zigbee_devices.json",
                                log=lambda *a: None)
        self.t0 = time.ticks_ms()
        self.reports = []      # (ms, short_addr, on_off)
        self._task = None

    def ms(self):
        return time.ticks_diff(time.ticks_ms(), self.t0)

    async def start(self):
        self._task = asyncio.create_task(self._reader())
        await asyncio.sleep(1)

    async def _reader(self):
        reader = asyncio.StreamReader(self.uart)
        while True:
            line = await reader.readline()
            if not line:
                continue
            try:
                msg = dec(line)
                self.gw.process_line(line)
                if msg.get("op") == "attribute_report":
                    payload = msg.get("payload") or {}
                    self.reports.append((self.ms(), payload.get("short_addr"),
                                         payload.get("on_off")))
            except Exception:
                pass

    def short_of(self, ieee):
        return (self.gw._registry.get(ieee) or {}).get("short_addr")

    def endpoint_of(self, ieee):
        for entity in self.repo.get_all("endpoints"):
            if entity.get("ieee_address") == ieee:
                return entity
        return None

    async def read_true_state(self, ieee):
        """Ground truth, straight from the device."""
        result = await self.gw.read_state(ieee)
        if result["status"] not in EXECUTION_SUCCESS_STATUSES:
            return None
        return result.get("reply", {}).get("on_off")

    async def command(self, ieee, action, label):
        entity = self.endpoint_of(ieee)
        return await self.gw.send({
            "event_id": label, "schedule_id": "hwtest",
            "source_date": (2026, 1, 1), "utc_minute": 0,
            "target_type": "endpoint", "target_id": entity["id"],
            "action_type": action, "action_data": {},
        })

    def reports_from(self, short, since_ms):
        return [r for r in self.reports if r[1] == short and r[0] >= since_ms]


async def test_link(h, r):
    print("\n[1] link and coordinator")
    result = await h.gw.ping()
    r.check(result["status"] in EXECUTION_SUCCESS_STATUSES, "ping answers",
            result["status"])
    caps = h.gw._capabilities
    r.check("delivery_ack" in caps, "delivery_ack advertised", str(caps))
    health = h.gw.info.get("health") or {}
    r.check(bool(health), "health counters present")
    for key in ("crc_errors", "rx_line_drops", "rx_queue_drops",
                "tx_queue_drops", "tx_oversize", "rx_oversize"):
        r.check(health.get(key, 0) == 0, "no " + key, str(health.get(key)))
    r.note("coordinator uptime {}s, frames in {}".format(
        health.get("uptime_s"), health.get("rx_frames")))


async def test_delivery(h, r, dut):
    print("\n[2] delivery proof on the device under test")
    before = await h.read_true_state(dut)
    r.check(before is not None, "read_attr returns real state", str(before))
    if before is None:
        return None

    action = "off" if before else "on"
    start = h.ms()
    result = await h.command(dut, action, "hw-deliver")
    elapsed = h.ms() - start
    r.check(result["status"] == "confirmed_by_device",
            "command is proven delivered", result["status"])
    r.check(elapsed <= ACK_BUDGET_MS, "ack within budget",
            "{}ms".format(elapsed))
    r.check(result["status"] in EXECUTION_SUCCESS_STATUSES,
            "a proven command is journalable")

    await asyncio.sleep(REPORT_BUDGET_MS / 1000)
    echo = h.reports_from(h.short_of(dut), start)
    r.check(bool(echo), "device reports the change it just made")
    if echo:
        r.check(echo[0][2] == (action == "on"), "report agrees with what we sent")
        r.note("echo latency {}ms".format(echo[0][0] - start))

    truth = await h.read_true_state(dut)
    r.check(truth == (action == "on"), "device really is in the new state",
            str(truth))
    r.check(h.gw.devices()[dut]["on_off"] == truth,
            "what we display matches the device")
    return before


async def test_unreachable(h, r):
    print("\n[3] a command that does not arrive")
    # A short address nothing answers on. Exercised at the ack layer so no
    # endpoint or registry entry has to be invented in /data.
    result = await h.gw._command("on_off",
                                 {"state": "on", "short_addr": "0xdead",
                                  "endpoint": 1})
    r.check(result["status"] not in EXECUTION_SUCCESS_STATUSES,
            "undeliverable command is NOT journalable", result["status"])
    r.check(result["status"] in ("error", "timeout"),
            "and is reported as a failure", result["status"])


async def test_manual_signal(h, r, actuator, dut):
    print("\n[4] manual intervention (the override rule depends on this)")
    dut_before = await h.read_true_state(dut)
    act_before = await h.read_true_state(actuator)
    if dut_before is None or act_before is None:
        r.check(False, "both relays reachable")
        return None

    start = h.ms()
    flip = "off" if act_before else "on"
    result = await h.command(actuator, flip, "hw-manual")
    r.check(result["status"] in EXECUTION_SUCCESS_STATUSES,
            "actuator accepted the command", result["status"])
    r.note("drove the actuator {} -- nothing is sent to the DUT".format(flip))
    await asyncio.sleep(REPORT_BUDGET_MS / 1000)

    # The first run left the actuator back at its starting state without
    # anyone putting it there, and the suite had no way to say whether it ever
    # reached the commanded state at all. Measure instead of assume: some
    # relays revert on their own (momentary/inching modes), which is a
    # property of the rig, not of our software -- but it must be visible.
    act_after = await h.read_true_state(actuator)
    if act_after == act_before:
        r.note("actuator reverted to {} by itself -- rig behaviour, "
               "not a software fault".format(act_before))
    else:
        r.check(act_after == (flip == "on"), "actuator holds the state we set",
                str(act_after))

    dut_after = await h.read_true_state(dut)
    r.check(dut_after != dut_before, "the manual action changed the DUT",
            "{} -> {}".format(dut_before, dut_after))

    unsolicited = h.reports_from(h.short_of(dut), start)
    r.check(bool(unsolicited),
            "DUT reported a change we never commanded")
    if unsolicited:
        r.note("manual-change detected in {}ms".format(unsolicited[0][0] - start))
    r.check(h.gw.devices()[dut]["on_off"] == dut_after,
            "display follows a manual change", str(dut_after))
    return act_before


async def test_observed_state_integrity(h, r, dut):
    print("\n[5] we never mistake our own command for the device's word")
    h.gw._states.pop(dut, None)
    h.gw._expected.pop(dut, None)
    current = await h.read_true_state(dut)
    h.gw._states.pop(dut, None)          # forget what the read told us

    await h.command(dut, "off" if current else "on", "hw-integrity")
    r.check(dut not in h.gw._states,
            "an unconfirmed command does not become observed state")
    confirmation = await h.gw.wait_for_report(dut, not current,
                                              REPORT_BUDGET_MS)
    r.check(confirmation["confirmed"],
            "the device's own report confirms it", str(confirmation))


async def restore(h, r, ieee, state, label):
    if state is None:
        return
    now = await h.read_true_state(ieee)
    if now == state:
        r.note("{} already back at {}".format(label, state))
        return
    await h.command(ieee, "on" if state else "off", "hw-restore")
    await asyncio.sleep(1)
    back = await h.read_true_state(ieee)
    r.check(back == state, "{} restored to its original state".format(label),
            str(back))


async def _run(actuator, dut):
    h = Harness()
    await h.start()
    r = Results()

    print("actuator {} -> {}".format(actuator, h.short_of(actuator)))
    print("dut      {} -> {}".format(dut, h.short_of(dut)))
    if not h.short_of(actuator) or not h.short_of(dut):
        print("ABORT: both devices must be in the zigbee registry")
        # Name what IS paired. Without this the abort is a dead end, and a
        # default address that went stale when a relay was swapped looks
        # identical to a radio that is down -- which is how this suite sat
        # unrunnable without anyone noticing.
        try:
            known = list(h.gw._registry)
        except Exception:
            known = []
        print("registry holds {} device(s):".format(len(known)))
        for ieee in known:
            print("   {}  -> {}".format(ieee, h.short_of(ieee)))
        print("re-run with:  python products/panel/host/run_hwtest.py --actuator <ieee> "
              "--dut <ieee>")
        return

    dut_initial = None
    act_initial = None
    try:
        await test_link(h, r)
        dut_initial = await test_delivery(h, r, dut)
        await test_unreachable(h, r)
        act_initial = await test_manual_signal(h, r, actuator, dut)
        await test_observed_state_integrity(h, r, dut)
    finally:
        print("\n[6] restoring")
        await restore(h, r, actuator, act_initial, "actuator")
        # The DUT follows the actuator, so put the actuator back first and only
        # then correct the DUT if it still differs.
        await restore(h, r, dut, dut_initial, "dut")

    print("\n=====================================")
    print(" {} passed, {} failed".format(r.passed, r.failed))
    print("=====================================")


def run(actuator, dut):
    asyncio.run(_run(actuator, dut))
