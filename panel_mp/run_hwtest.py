"""Run the on-device hardware tests, then put the panel back the way it was.

Handles the three chores that made every manual probe session tedious:
finding the panel (the CH340 renumbers itself between COM7 and COM8 on its
own), stopping main.py so the REPL is usable without the display's DMA racing
the transfer, and -- the one that kept being forgotten -- restoring main.py
afterwards so the screen comes back.

    python panel_mp/run_hwtest.py
    python panel_mp/run_hwtest.py --actuator <ieee> --dut <ieee>
"""

import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# The bench rig: the older relay drives the newer one's switch input, so
# commanding it stands in for a person at the wall switch.
DEFAULT_ACTUATOR = "a4:c1:38:6b:47:9d:c2:55"
DEFAULT_DUT = "f0:44:d3:ff:fe:6e:d6:e2"

CH340_VID_PID = (0x1A86, 0x7522)


def find_panel():
    from serial.tools import list_ports
    for port in sorted(list_ports.comports(), key=lambda p: p.device):
        if (port.vid, port.pid) == CH340_VID_PID:
            return port.device
    return None


def mpremote(port, *args):
    return subprocess.call(
        [sys.executable, "-m", "mpremote", "connect", port] + list(args))


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
    if mpremote(port, "cp", os.path.join(HERE, "hwtest.py"), ":hwtest.py") != 0:
        return 1

    print("== running ==")
    rc = mpremote(port, "exec", "import hwtest; hwtest.run({!r}, {!r})".format(
        args.actuator, args.dut))

    if not args.keep_repl:
        print("== restoring main.py ==")
        mpremote(port, "cp", os.path.join(HERE, "main.py"), ":main.py")
        mpremote(port, "reset")
        print("screen is coming back")
    return rc


if __name__ == "__main__":
    sys.exit(main())
