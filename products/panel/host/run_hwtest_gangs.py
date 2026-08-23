"""Prove on hardware that a two-gang switch keeps one state cell per gang.

    python products/panel/host/run_hwtest_gangs.py
    python products/panel/host/run_hwtest_gangs.py --dut <ieee>

This is the measurement task 26a rests on, and it exists as a script because
the host suite cannot make it. Every one of the 496 host tests passed against
the broken code too: a two-gang device is one ieee with two relays, and the
only place that fact is real is the bench. The bug was first seen here -- a
wait on gang 1 answered ``observed: True`` while gang 1 was off, because gang 2
had just reported -- and the proof that it is gone has to come from the same
place.

It is a file rather than a snippet pasted per run because the same measurement
is needed three times (26a, 26b, and the add-device screen), and a probe
rewritten each time carries a new bug each time. That is not a guess: rewriting
it twice in one afternoon produced a ``mpremote rm :main.py`` that races the
display's DMA, and a raw ``exec`` that hung for five minutes with main.py still
deleted. Both are avoided here by going through run_common, like every other
runner in this directory.

**It returns an exit code**, and three of them, because two of the outcomes are
not the same answer:

    0  each gang kept its own state
    1  measured, and the cell lied -- the 26a bug is present
    2  could not measure: the relays did not answer, or no multi-gang device

A script that only prints PASS/FAIL is a script someone reads past, and one
that collapses 1 and 2 is worse: the first run of this file reported the 26a
bug at a bench whose mains happened to be off.

The DUT is found rather than hardcoded. run_hwtest.py's baked-in addresses have
pointed at unpaired devices for a while, and a run against a device that is not
there fails for a reason that has nothing to do with the code under test. Any
device advertising OnOff on two or more endpoints will do.
"""

import argparse
import os
import subprocess
import sys

from run_common import find_panel, restore_main, run_on_device, sync_core

HERE = os.path.dirname(os.path.abspath(__file__))
# host/ -> panel/ -> products/ -> repo root.
ROOT = os.path.abspath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
DEVICE = os.path.join(HERE, os.pardir, "device")

RUN_TIMEOUT_S = 180
CLUSTER_ON_OFF = 6

# Printed between sentinels so the host decides, not the eye. Anything the
# device cannot do prints ERR and the host turns that into a non-zero exit
# rather than a green run with a sad line in the middle of it.
PROBE = '''
import asyncio
from machine import UART
from smart_kosher.adapters import JsonRepository
from smart_kosher.adapters.zigbee_gateway import ZigbeeGateway
from smart_kosher.ports.device_gateway import EXECUTION_SUCCESS_STATUSES

WANTED = {dut!r}
CLUSTER_ON_OFF = 6


def _pick(registry):
    """A device with OnOff on two or more endpoints, or None."""
    if WANTED:
        return WANTED if WANTED in registry else None
    for ieee in sorted(registry):
        entry = registry[ieee]
        clusters = entry.get("clusters") or {{}}
        gangs = [ep for ep in (entry.get("endpoints") or [])
                 if CLUSTER_ON_OFF in (clusters.get(str(ep)) or [])]
        if len(gangs) >= 2:
            return ieee
    return None


async def go():
    gw = ZigbeeGateway(UART(1, baudrate=115200, tx=5, rx=19, timeout=0,
                            rxbuf=2048),
                       JsonRepository("/data"),
                       registry_path="/data/zigbee_devices.json",
                       log=lambda *a: None)

    async def reader():
        stream = asyncio.StreamReader(gw._uart)
        while True:
            line = await stream.readline()
            if line:
                try:
                    gw.process_line(line)
                except Exception:
                    pass

    asyncio.create_task(reader())
    await asyncio.sleep(1)
    print("BEGIN")
    try:
        dut = _pick(gw._registry)
        if dut is None:
            print("ERR|no device with OnOff on two endpoints in the registry")
            print("END")
            return
        entry = gw._registry[dut]
        # Read, never hardcoded: it changed to 0x3c20 on a re-pair and will
        # change again.
        short = entry["short_addr"]
        clusters = entry.get("clusters") or {{}}
        gangs = [ep for ep in entry.get("endpoints") or []
                 if CLUSTER_ON_OFF in (clusters.get(str(ep)) or [])]
        low, high = gangs[0], gangs[1]
        print("dut|{{}}".format(dut))
        print("short|{{}}".format(short))
        print("gangs|{{}}|{{}}".format(low, high))

        async def switch(endpoint, state):
            return (await gw._command(
                "on_off", {{"state": state, "short_addr": short,
                           "endpoint": endpoint}}))["status"]

        # The measurement: the low gang off, the high gang on. Before 26a the
        # second report overwrote the first and devices() answered True for a
        # relay that is off.
        low_status = await switch(low, "off")
        high_status = await switch(high, "on")
        print("cmd_low|{{}}".format(low_status))
        print("cmd_high|{{}}".format(high_status))
        # Said here rather than inferred on the host, and against the real
        # success set rather than one literal. A relay that never answered
        # tells us nothing about which cell its report would have landed in.
        print("reachable|{{}}".format(
            low_status in EXECUTION_SUCCESS_STATUSES
            and high_status in EXECUTION_SUCCESS_STATUSES))
        await asyncio.sleep(4)

        item = gw.devices()[dut]
        print("on_off|{{}}".format(item.get("on_off")))
        per_gang = item.get("endpoint_on_off") or {{}}
        print("per_gang|" + ",".join(
            "{{}}:{{}}".format(ep, per_gang[ep]) for ep in sorted(per_gang)))
    finally:
        try:
            await switch(high, "off")
            print("restored|high gang off")
        except Exception as exc:
            print("ERR|could not restore the high gang: {{}}".format(exc))
        print("END")

asyncio.run(go())
'''


def _read_device(port, dut):
    print("== syncing the brain to /lib ==")
    if not sync_core(port, ROOT):
        return None
    print("== running ==")
    return run_on_device(
        port, PROBE.format(dut=dut), RUN_TIMEOUT_S, capture=True,
        hint="the last line between BEGIN and END is where it stopped")


def _fields(output):
    found = {}
    for line in output.splitlines():
        if "|" not in line:
            continue
        key, _, rest = line.strip().partition("|")
        found[key] = rest
    return found


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port")
    parser.add_argument("--dut", default="",
                        help="ieee of the multi-gang device; found if omitted")
    args = parser.parse_args()

    port = args.port or find_panel()
    if port is None:
        print("No panel found (CH340 1A86:7522). Is its USB connected?")
        return 1
    print("panel on {}".format(port))

    print("== stopping main.py (the screen goes blank for the run) ==")
    if subprocess.call([sys.executable, os.path.join(HERE, "clean_board.py"),
                        port]) != 0:
        print("could not reach a clean REPL")
        return 1

    # Same shape as the other runners: the device work is a function and the
    # restore is a finally, so a failed upload or a board that goes quiet still
    # gets its screen back.
    try:
        result = _read_device(port, args.dut)
    finally:
        restored = restore_main(port, DEVICE)
    if not restored or result is None:
        return 1

    output = result.stdout or ""
    if "BEGIN" not in output or "END" not in output:
        print("device produced no usable output:")
        print(output[:1000])
        return 1

    found = _fields(output)
    if "ERR" in found:
        print("!! {}".format(found["ERR"]))
        return 2

    print()
    print("dut      : {}  short {}".format(found.get("dut"),
                                           found.get("short")))
    print("gangs    : {}".format(found.get("gangs")))
    print("commands : low off -> {} | high on -> {}".format(
        found.get("cmd_low"), found.get("cmd_high")))
    print("on_off          = {}".format(found.get("on_off")))
    print("endpoint_on_off = {}".format(found.get("per_gang")))
    print()

    # Nothing below can mean anything if the relays never answered. Told
    # apart on purpose: the first run of this script reported the 26a bug at a
    # bench whose mains were off, which is a green-shaped lie in the other
    # direction -- a red that names the wrong cause.
    if found.get("reachable") != "True":
        print("INCONCLUSIVE  the device did not answer (low {} / high {})."
              .format(found.get("cmd_low"), found.get("cmd_high")))
        print("              This says nothing about 26a. Check the relays "
              "have mains and are still joined.")
        return 2

    low, high = (found.get("gangs") or "|").split("|")[:2]
    failures = []
    # The whole point. on_off is the entry's own endpoint, so with the low gang
    # off it must read False -- the exact inverse of the observed: True this
    # bug was first caught with.
    if found.get("on_off") != "False":
        failures.append(
            "on_off is {} -- the high gang's report landed in the low gang's "
            "cell, which is the bug 26a fixes".format(found.get("on_off")))
    expected = "{}:False,{}:True".format(low, high)
    if found.get("per_gang") != expected:
        failures.append("endpoint_on_off is {} -- expected {}".format(
            found.get("per_gang"), expected))

    for line in failures:
        print("FAIL  {}".format(line))
    if failures:
        return 1
    print("PASS  each gang keeps its own state")
    return 0


if __name__ == "__main__":
    sys.exit(main())
