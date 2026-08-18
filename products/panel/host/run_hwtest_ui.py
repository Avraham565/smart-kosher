"""Run the on-device UI tests, then put the panel back the way it was.

Same chores as run_hwtest.py -- find the panel, stop main.py so the REPL is
usable without the display's DMA racing the transfer, restore main.py after --
but this suite brings the display up itself, because what it tests is the
screen.

    python products/panel/host/run_hwtest_ui.py
"""

import argparse
import os
import subprocess
import sys

from run_common import find_panel, mpremote, restore_main, run_on_device, sync_core

HERE = os.path.dirname(os.path.abspath(__file__))
# host/ -> panel/ -> products/ -> repo root.
ROOT = os.path.abspath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
DEVICE = os.path.join(HERE, os.pardir, "device")
HWTEST = os.path.join(HERE, os.pardir, "hwtest")

# Uploaded before the run. city_picker is the component under test; the others
# are what it imports and may have changed alongside it. The suite itself comes
# from hwtest/; everything it exercises comes from device/.
#
# This list is the suite's import closure, and a name missing from it fails
# silently in the worst way: the module is already on the board from the last
# deploy, so nothing errors -- the run just tests the *old* copy and reports
# green. It happened to clock.py (shell.py imports it, and no test names it
# directly) and then to zone_picker.py, while the very test written to drive it
# was added.
#
# It is no longer kept by eye. tests/test_hwtest_payload_is_complete.py derives
# the closure from the source and fails if this list drifts either way, so the
# fix for "the run tested the old copy" is now a red suite on the host rather
# than a puzzled hour at the bench. Add an import, run the suite, follow it.
SUITE = "hwtest_ui.py"
PAYLOAD = ("city_picker.py", "settime.py", "zmanim_page.py",
           "keyboard.py", "widgets.py", "theme.py", "display.py", "shell.py",
           "clock.py", "bridge.py", "store.py", "hebdate.py", "reactive.py",
           # the paging work: the three list pages and their shared arithmetic
           "pager.py", "rooms_page.py", "room_page.py", "schedules_page.py",
           "zone_picker.py", "text_input.py", "dev_common.py", "toast.py",
           "sched_describe.py", "sched_labels.py",
           # Reachable only through imports that fire on a tap this suite never
           # makes (room -> device, schedules -> wizard, back -> home). Carried
           # anyway: the closure rule has no judgement in it, and judgement is
           # what failed here twice. Four file copies is the whole cost.
           "device_page.py", "schedule_add.py", "ui_home.py", "pages.py")

# The suite builds three screens and measures forty city names through each of
# them, then walks the three list pages up to twice their page capacity to
# measure how many rows really fit -- another few dozen screen builds. Call it
# two minutes on the board. Ten times that is not a slow board, it is one that
# stopped answering -- and unbounded, mpremote waits on the raw REPL for a
# terminator a reset board will never send, so the run hangs forever with
# main.py still deleted.
RUN_TIMEOUT_S = 600


def _run_suite(port):
    print("== uploading ==")
    if mpremote(port, "cp", os.path.join(HWTEST, SUITE), ":" + SUITE) != 0:
        return 1
    for name in PAYLOAD:
        if mpremote(port, "cp", os.path.join(DEVICE, name), ":" + name) != 0:
            return 1

    # The whole brain, not the three data files this used to refresh. The suite
    # runs against the core as much as against device/, and a core dependency
    # added in the repo but never copied here is the same stale-copy failure
    # the payload above exists to prevent -- it happened, on
    # MAX_ZMAN_OFFSET_MINUTES, and only failed loudly by luck.
    print("== syncing the brain to /lib ==")
    if not sync_core(port, ROOT):
        return 1

    print("== running ==")
    rc = run_on_device(
        port, "import hwtest_ui; raise SystemExit(0 if hwtest_ui.run() else 1)",
        RUN_TIMEOUT_S,
        hint="The last check printed above is the one it died on.")
    return 1 if rc is None else rc


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

    # Past this line main.py is gone from the board, so every way out of this
    # function has to put it back -- hence the finally. It used to be restored
    # on one path only, the successful one: an upload that failed, or a suite
    # that took the board down with it, returned straight out of here and left
    # the panel dark, with the restore skipped and nothing saying so. That is
    # the state a run is *most* likely to end in, because it is the state a bug
    # in the UI produces.
    rc = 1
    try:
        rc = _run_suite(port)
    finally:
        restored = args.keep_repl or restore_main(port, DEVICE)
    return rc if restored else 1


if __name__ == "__main__":
    sys.exit(main())
