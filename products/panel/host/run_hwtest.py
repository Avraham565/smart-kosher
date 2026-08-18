"""Run the on-device hardware tests, then put the panel back the way it was.

Handles the three chores that made every manual probe session tedious:
finding the panel (the CH340 renumbers itself between COM7 and COM8 on its
own), stopping main.py so the REPL is usable without the display's DMA racing
the transfer, and -- the one that kept being forgotten -- restoring main.py
afterwards so the screen comes back.

    python products/panel/host/run_hwtest.py
    python products/panel/host/run_hwtest.py --actuator <ieee> --dut <ieee>
"""

import argparse
import os
import subprocess
import sys

from run_common import find_panel, mpremote, restore_main, run_on_device, sync_core

HERE = os.path.dirname(os.path.abspath(__file__))
# host/ -> panel/ -> products/ -> repo root.
ROOT = os.path.abspath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
# Siblings of host/: what the board runs, and what is uploaded only for a test.
DEVICE = os.path.join(HERE, os.pardir, "device")
HWTEST = os.path.join(HERE, os.pardir, "hwtest")

SUITE = "hwtest.py"

# The bench rig: the older relay drives the newer one's switch input, so
# commanding it stands in for a person at the wall switch.
DEFAULT_ACTUATOR = "a4:c1:38:6b:47:9d:c2:55"
DEFAULT_DUT = "f0:44:d3:ff:fe:6e:d6:e2"

# The suite's own budgets are sub-second (ACK_BUDGET_MS 800, REPORT_BUDGET_MS
# 2000) with a couple of one-second settles, so it finishes in well under a
# minute. Five minutes is not a slow bench, it is a board that stopped
# answering -- and an unbounded run hangs here with main.py still deleted.
RUN_TIMEOUT_S = 300


def _run_suite(port, args):
    print("== uploading hwtest.py ==")
    if mpremote(port, "cp", os.path.join(HWTEST, SUITE), ":" + SUITE) != 0:
        return 1

    # This suite is almost entirely core: the gateway, the repository, the
    # codec and the delivery vocabulary all come from /lib. Nothing refreshed
    # them, so it could pass against a brain several commits old.
    print("== syncing the brain to /lib ==")
    if not sync_core(port, ROOT):
        return 1

    print("== running ==")
    rc = run_on_device(
        port,
        "import hwtest; hwtest.run({!r}, {!r})".format(args.actuator, args.dut),
        RUN_TIMEOUT_S,
        hint="The last assertion printed above is the one it died on.")
    return 1 if rc is None else rc


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port")
    parser.add_argument("--actuator", default=DEFAULT_ACTUATOR)
    parser.add_argument("--dut", default=DEFAULT_DUT)
    parser.add_argument("--keep-repl", action="store_true",
                        help="leave main.py off (screen stays blank)")
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

    # Past this line main.py is gone from the board, so every way out has to put
    # it back -- hence the finally. It used to be restored on the success path
    # only: an upload that failed returned straight out of here, and a board that
    # died mid-run hung the unbounded exec forever, both leaving the panel dark
    # with nothing saying so.
    rc = 1
    try:
        rc = _run_suite(port, args)
    finally:
        restored = args.keep_repl or restore_main(port, DEVICE)
    return rc if restored else 1


if __name__ == "__main__":
    sys.exit(main())
