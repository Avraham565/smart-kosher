"""Flash the panel's firmware without losing the user's data.

    python products/panel/host/flash.py --bin <path-to-firmware.bin>

Until 2026-08-27 there was no script for this. deploy.ps1 deploys *files*;
nothing in the repo flashed *firmware*, so it was done by hand:

    python -m esptool --chip esp32s3 -p COM7 -b 460800 \
        write-flash --erase-all 0x0 <bin>

``--erase-all`` wipes the whole VFS, and /data is in it -- devices, zones,
schedules, settings, the journal. That was remembered three times in one
afternoon. A fourth time is not guaranteed, and nothing downstream would say
so: the panel simply boots empty, which looks like a new board rather than
like a loss.

So the sequence is here instead of in someone's head, in the order that makes
each step recoverable:

    1  back up :/data to the host, and verify it by SIZE
    2  archive the binary about to be flashed, so "what was on the board" is
       answerable later
    3  flash
    4  deploy.ps1 -- fonts, modules, the brain, main.py
    5  put /data back, and verify it by SIZE

Sizes rather than exit codes throughout. mpremote reports a successful copy
from the host side, and the host side is not where the file landed; task 46 is
two occasions when main.py came back at zero bytes after a copy that said it
worked. What is at stake here is larger.

This does not build. Building overwrites build/*.bin in place and that is the
only copy of what is currently on the board -- back it up before you build, as
products/panel/firmware/lvgl_micropython/README.md says.
"""

import argparse
import datetime
import os
import shutil
import subprocess
import sys

from run_common import (
    board_listing,
    compare_listings,
    find_panel,
    local_listing,
    mpremote,
)

HERE = os.path.dirname(os.path.abspath(__file__))
DEVICE = os.path.join(HERE, os.pardir, "device")

# Outside the repo: this is a per-board record of user data and of which
# binary was on the panel when, and neither belongs in version control.
BACKUP_ROOT = os.path.join(os.path.expanduser("~"), "panel_backup")

DATA_DIR = ":/data"


def _stamp():
    return datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")


def back_up_data(port, dest):
    """Copy :/data to ``dest``, verified against the board's own listing.

    Returns the board listing on success, {} when the board genuinely has no
    /data, and None when something went wrong -- which the caller must treat
    as a refusal to flash, not as an empty backup.
    """
    board = board_listing(port, DATA_DIR)
    if board is None:
        print("!! could not read {} -- refusing to flash. If this board "
              "really has no data, say so with --allow-empty-data."
              .format(DATA_DIR))
        return None
    if not board:
        print("   {} is empty on the board".format(DATA_DIR))
        return {}

    os.makedirs(dest, exist_ok=True)
    if mpremote(port, "fs", "cp", "-r", DATA_DIR, dest + os.sep) != 0:
        print("!! the copy off the board failed")
        return None

    landed = local_listing(os.path.join(dest, "data"))
    problems = compare_listings(board, landed)
    if problems:
        print("!! the backup does not match the board:")
        for problem in problems:
            print("     " + problem)
        return None
    print("   {} files backed up and verified".format(len(board)))
    return board


def restore_data(port, source, expected):
    """Put ``source``/data back on the board and verify it by size."""
    if not expected:
        return True
    if mpremote(port, "fs", "cp", "-r", os.path.join(source, "data"),
                ":") != 0:
        print("!! the copy back to the board failed")
        return False
    problems = compare_listings(expected, board_listing(port, DATA_DIR) or {})
    if problems:
        print("!! {} did not come back intact:".format(DATA_DIR))
        for problem in problems:
            print("     " + problem)
        print("   the backup is still at {} -- do not reflash over it"
              .format(source))
        return False
    print("   {} files restored and verified".format(len(expected)))
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bin", required=True,
                        help="firmware .bin to write at 0x0")
    parser.add_argument("--port")
    parser.add_argument("--allow-empty-data", action="store_true",
                        help="proceed even though :/data could not be read "
                             "or is empty (a virgin board)")
    parser.add_argument("--no-deploy", action="store_true",
                        help="skip deploy.ps1; the board will have firmware "
                             "and an empty filesystem")
    args = parser.parse_args()

    if not os.path.isfile(args.bin):
        print("no such firmware: {}".format(args.bin))
        return 1

    port = args.port or find_panel()
    if port is None:
        print("No panel found (CH340 1A86:7522). Is its USB connected?")
        print("The port vanishing entirely is a loose cable, not a busy "
              "port -- mpremote calls it 'in use by another program' either "
              "way, so check the listing before hunting for orphans.")
        return 1
    print("panel on {}".format(port))

    session = os.path.join(BACKUP_ROOT, _stamp())
    print("== 1) backing up {} to {} ==".format(DATA_DIR, session))
    expected = back_up_data(port, session)
    if expected is None:
        if not args.allow_empty_data:
            return 1
        print("   continuing without a backup because --allow-empty-data")
        expected = {}

    print("== 2) archiving the firmware being flashed ==")
    os.makedirs(session, exist_ok=True)
    archived = os.path.join(session, os.path.basename(args.bin))
    shutil.copy2(args.bin, archived)
    print("   {}".format(archived))

    print("== 3) flashing (this erases the filesystem) ==")
    if subprocess.call([sys.executable, "-m", "esptool", "--chip", "esp32s3",
                        "-p", port, "-b", "460800", "write-flash",
                        "--erase-all", "0x0", args.bin]) != 0:
        print("!! the flash failed. {} still holds the data.".format(session))
        return 1

    if args.no_deploy:
        print("== 4) skipped, and so is the restore: an empty board has "
              "nowhere to put /data ==")
        print("   when you do deploy, restore with:")
        print("   python -m mpremote connect {} fs cp -r {} :"
              .format(port, os.path.join(session, "data")))
        return 0

    print("== 4) deploying ==")
    deploy = os.path.join(HERE, "deploy.ps1")
    if subprocess.call(["powershell", "-NoProfile", "-ExecutionPolicy",
                        "Bypass", "-File", deploy, "-Port", port]) != 0:
        print("!! deploy.ps1 failed. The firmware is flashed and the board "
              "has no filesystem; {} still holds the data.".format(session))
        return 1

    # deploy.ps1 finishes by resetting into main.py, so the display is up and
    # its DMA is running again. Every warning in this directory says not to
    # copy onto a board in that state, so stop it first -- and deploy.ps1's
    # own last step is the thing that put it back.
    print("== 5) restoring {} ==".format(DATA_DIR))
    if subprocess.call([sys.executable, os.path.join(HERE, "clean_board.py"),
                        port]) != 0:
        print("!! could not reach a clean REPL to restore the data; "
              "it is at {}".format(session))
        return 1
    ok = restore_data(port, session, expected)
    from run_common import restore_main
    restored = restore_main(port, DEVICE)
    if not (ok and restored):
        return 1

    print("")
    print("done. firmware, files and data are all on the board, and the")
    print("backup at {} is what to come back to.".format(session))
    return 0


if __name__ == "__main__":
    sys.exit(main())
