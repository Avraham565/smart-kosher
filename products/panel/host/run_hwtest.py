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

from run_common import find_panel, mpremote

HERE = os.path.dirname(os.path.abspath(__file__))
# Siblings of host/: what the board runs, and what is uploaded only for a test.
DEVICE = os.path.join(HERE, os.pardir, "device")
HWTEST = os.path.join(HERE, os.pardir, "hwtest")

# The bench rig: the older relay drives the newer one's switch input, so
# commanding it stands in for a person at the wall switch.
DEFAULT_ACTUATOR = "a4:c1:38:6b:47:9d:c2:55"
DEFAULT_DUT = "f0:44:d3:ff:fe:6e:d6:e2"


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

    print("== uploading hwtest.py ==")
    if mpremote(port, "cp", os.path.join(HWTEST, "hwtest.py"), ":hwtest.py") != 0:
        return 1

    print("== running ==")
    rc = mpremote(port, "exec", "import hwtest; hwtest.run({!r}, {!r})".format(
        args.actuator, args.dut))

    if not args.keep_repl:
        print("== restoring main.py ==")
        mpremote(port, "cp", os.path.join(DEVICE, "main.py"), ":main.py")
        mpremote(port, "reset")
        print("screen is coming back")
    return rc


if __name__ == "__main__":
    sys.exit(main())
