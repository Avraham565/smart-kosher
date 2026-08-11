"""Run the on-device UI tests, then put the panel back the way it was.

Same chores as run_hwtest.py -- find the panel, stop main.py so the REPL is
usable without the display's DMA racing the transfer, restore main.py after --
but this suite brings the display up itself, because what it tests is the
screen.

    python panel_mp/run_hwtest_ui.py
"""

import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

CH340_VID_PID = (0x1A86, 0x7522)

# Uploaded before the run. city_picker is the component under test; the others
# are what it imports and may have changed alongside it.
PAYLOAD = ("hwtest_ui.py", "city_picker.py", "settime.py", "zmanim_page.py",
           "keyboard.py", "widgets.py", "theme.py", "display.py", "shell.py",
           "bridge.py", "store.py", "hebdate.py", "reactive.py")


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
    parser.add_argument("--keep-repl", action="store_true",
                        help="leave main.py off (screen stays blank)")
    args = parser.parse_args()

    port = args.port or find_panel()
    if port is None:
        print("No panel found (CH340 1A86:7522). Is its USB connected?")
        return 1
    print("panel on {}".format(port))

    print("== stopping main.py (so the transfer does not race the DMA) ==")
    if subprocess.call([sys.executable, os.path.join(HERE, "clean_board.py"),
                        port]) != 0:
        print("could not reach a clean REPL")
        return 1

    print("== uploading ==")
    for name in PAYLOAD:
        if mpremote(port, "cp", os.path.join(HERE, name), ":" + name) != 0:
            return 1

    # The search logic lives in the brain package, so refresh the city data too.
    print("== refreshing city data ==")
    mpremote(port, "cp",
             os.path.join(HERE, "..", "src", "smart_kosher", "data", "cities.json"),
             ":/lib/smart_kosher/data/cities.json")
    mpremote(port, "cp",
             os.path.join(HERE, "..", "src", "smart_kosher", "data", "cities.py"),
             ":/lib/smart_kosher/data/cities.py")
    mpremote(port, "cp",
             os.path.join(HERE, "..", "src", "smart_kosher", "data", "__init__.py"),
             ":/lib/smart_kosher/data/__init__.py")

    print("== running ==")
    rc = mpremote(port, "exec",
                  "import hwtest_ui; raise SystemExit(0 if hwtest_ui.run() else 1)")

    if not args.keep_repl:
        # clean_board.py DELETED main.py to get a DMA-free REPL, so it has to be
        # copied back -- a reset alone boots the board to a bare prompt and the
        # screen stays black. This step was once a reset with no copy, and the
        # only symptom was a dead panel long after the run reported success.
        print("== restoring main.py ==")
        if mpremote(port, "cp", os.path.join(HERE, "main.py"), ":main.py") != 0:
            print("!! could not restore main.py -- the panel will boot to the "
                  "REPL with a black screen. Re-run:")
            print("   python -m mpremote connect {} cp panel_mp/main.py :main.py"
                  .format(port))
            return 1
        mpremote(port, "reset")
        print("screen is coming back")
    return rc


if __name__ == "__main__":
    sys.exit(main())
