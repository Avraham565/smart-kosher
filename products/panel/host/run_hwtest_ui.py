"""Run the on-device UI tests, then put the panel back the way it was.

Same chores as run_hwtest.py -- find the panel, stop main.py so the REPL is
usable without the display's DMA racing the transfer, restore main.py after --
but this suite brings the display up itself, because what it tests is the
screen.

    python products/panel/host/run_hwtest_ui.py
"""

import argparse
import datetime
import json
import os
import subprocess
import sys

from run_common import (
    find_panel,
    mpremote,
    restore_main,
    run_suite_on_device,
    suite_verdict,
    sync_core,
)

HERE = os.path.dirname(os.path.abspath(__file__))
# host/ -> panel/ -> products/ -> repo root.
ROOT = os.path.abspath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
DEVICE = os.path.join(HERE, os.pardir, "device")
HWTEST = os.path.join(HERE, os.pardir, "hwtest")

# The touch controller's four tuned registers live in the GT911's own flash.
# They survive power-off, a reflash and --erase-all, and nothing in this repo
# can see them -- so before this file existed the only trace of them was prose
# in a task list. --probe-touch rewrites the "observed" half on every run, and
# tests/test_touch_registers_match_the_baseline.py compares it against the
# "expected" half, which is written by hand and changed only on purpose.
TOUCH_RECORD = os.path.join(HERE, "touch_registers.json")
TOUCH_CONFIG_MARK = "TOUCH_CONFIG"

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
           "add_device_page.py",
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


def _run_probe(port, call, hint, record=None):
    """Drive one probe instead of the suite. A person reads the panel.

    Scored by PROBE_DONE rather than by suite_verdict, and the difference is
    deliberate: these runs have no pass or fail in them. The exit code says the
    probe reached the end without the board dying, and nothing else. What was
    seen is the finding, and only a person can supply it.

    One scorer for every probe, taking the call as an argument. A second copy
    of "look for PROBE_DONE" is the same hand-maintained duplicate that has
    already cost this project three false greens, and it would be a duplicate
    of the *verdict* -- the one place a copy is worst.
    """
    lines = run_suite_on_device(
        port, "import hwtest_ui; hwtest_ui." + call, RUN_TIMEOUT_S, hint=hint)
    # Before the verdict, and deliberately: a probe that died halfway still
    # read the controller before it died, and that reading is worth keeping.
    if record is not None:
        record(lines)
    if any(line.strip().startswith("PROBE_DONE") for line in lines):
        return 0
    print("!! the probe never reached the end -- nothing was measured")
    return 1


def _record_touch_config(lines, port):
    """Turn the probe's TOUCH_CONFIG line into a file the repo can diff.

    The task this closes (59) is not "document the four numbers" -- they were
    already written down in prose, and prose is not a baseline. It is to leave
    a RECORD, so that the next reading can be compared against this one by
    something other than a person remembering.

    The LAST marker wins. A run that writes new values prints the line twice:
    once for what the controller held on arrival, once for what it holds after
    the save. Only the second describes the board that is now on the bench.

    Only the "observed" half is touched. "expected" is the tuned baseline and
    is changed by hand, on purpose -- if this function rewrote both, the test
    that compares them would agree with itself forever, which is the false
    green CLAUDE.md spends a section on.
    """
    marks = [ln for ln in lines if ln.strip().startswith(TOUCH_CONFIG_MARK + " ")]
    if not marks:
        print("!! the probe printed no {} line, so nothing was recorded. The "
              "board may not have reached the controller at all."
              .format(TOUCH_CONFIG_MARK))
        return
    observed = {}
    for pair in marks[-1].split()[1:]:
        key, _, value = pair.partition("=")
        try:
            observed[key] = int(value)
        except ValueError:
            print("!! could not read {!r} out of the probe line; nothing "
                  "recorded".format(pair))
            return
    observed["read_at"] = datetime.datetime.now(
        datetime.timezone.utc).replace(microsecond=0).isoformat()
    observed["port"] = port

    try:
        with open(TOUCH_RECORD, encoding="utf-8") as handle:
            record = json.load(handle)
    except (OSError, ValueError):
        record = {}
        print("!! {} was missing or unreadable, so it is being created with "
              "an observed half only. Fill in \"expected\" by hand before "
              "trusting the test.".format(os.path.basename(TOUCH_RECORD)))
    record["observed"] = observed
    with open(TOUCH_RECORD, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(record, handle, indent=2)
        handle.write("\n")
    print("== recorded to {} ==".format(os.path.relpath(TOUCH_RECORD, ROOT)))
    expected = record.get("expected")
    if expected:
        drift = [k for k in ("press_level", "leave_level", "shake_count",
                             "refresh_rate")
                 if observed.get(k) != expected.get(k)]
        if drift:
            print("!! the controller does not match the baseline: {}".format(
                ", ".join("{} is {} not {}".format(
                    k, observed.get(k), expected.get(k)) for k in drift)))
        else:
            print("   matches the baseline on all four registers")


def _run_suite(port, args=None):
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
    # Scored by what the suite printed, not by what mpremote returned: it
    # returns 0 either way (finding 44), so SystemExit here was decorative.
    if args is not None and args.probe_striping:
        return _run_probe(
            port,
            "probe_screen_transition_striping(invalidate={})".format(
                args.invalidate),
            "The probe died mid-run; the panel may be mid-transition.")
    if args is not None and args.probe_home_press:
        return _run_probe(
            port,
            "probe_home_card_press(single_draw_buffer={}, mode={!r})".format(
                bool(args.single_draw_buffer),
                "width" if args.vary_width else "draws"),
            "The probe died mid-run; the card may be left pressed.")
    if args is not None and args.probe_touch:
        # Uploaded here and not in PAYLOAD on purpose. PAYLOAD is the suite's
        # closure over products/panel/device -- the product -- and this is an
        # upstream bench tool that the product never imports. See
        # host/vendor/README.md.
        vendor = os.path.join(HERE, "vendor", "gt911_extension.py")
        if mpremote(port, "cp", vendor, ":gt911_extension.py") != 0:
            print("!! could not upload gt911_extension.py; the controller's "
                  "own thresholds cannot be read")
            return 1
        return _run_probe(
            port,
            "probe_touch(press_level={}, leave_level={}, shake_count={}, "
            "refresh_rate={})".format(
                args.press_level, args.leave_level,
                args.shake_count, args.refresh_rate),
            "The probe died; if it was mid-save the controller config may be "
            "half written -- re-run to read it back before changing anything.",
            record=lambda lines: _record_touch_config(lines, port))
    if args is not None and args.probe_display_buffers:
        return _run_probe(
            port, "probe_display_buffers()",
            "The probe died during display.init(); nothing was counted.")
    lines = run_suite_on_device(
        port, "import hwtest_ui; hwtest_ui.run()", RUN_TIMEOUT_S,
        hint="The last check printed above is the one it died on.")
    return suite_verdict(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port")
    parser.add_argument("--keep-repl", action="store_true",
                        help="leave main.py off (screen stays blank)")
    # Mutually exclusive because each probe wants the whole panel to itself:
    # asked for both, one would silently win and the run would report on an
    # experiment nobody chose.
    probes = parser.add_mutually_exclusive_group()
    probes.add_argument("--probe-striping", action="store_true",
                        help="swap between two loaded screens and watch the "
                             "panel, instead of running the suite (task 47)")
    probes.add_argument("--probe-home-press", action="store_true",
                        help="press the real home card on a quiet board and "
                             "watch it, instead of running the suite (task 48)")
    probes.add_argument("--probe-display-buffers", action="store_true",
                        help="count the buffers the flashed RGB driver "
                             "allocates, instead of running the suite")
    probes.add_argument("--probe-touch", action="store_true",
                        help="report the touch controller's sampling rate and "
                             "sensitivity thresholds, instead of the suite")
    parser.add_argument("--press-level", type=int, default=None,
                        help="with --probe-touch: WRITE this press threshold "
                             "to the controller's flash (lower = more "
                             "sensitive). Read the current one first")
    parser.add_argument("--leave-level", type=int, default=None,
                        help="with --probe-touch: WRITE this release "
                             "threshold. Must stay below --press-level")
    parser.add_argument("--shake-count", type=int, default=None,
                        help="with --probe-touch: WRITE the de-jitter counts "
                             "(0x804F). High nibble release, low nibble "
                             "press; each count costs one report period")
    parser.add_argument("--refresh-rate", type=int, default=None,
                        help="with --probe-touch: WRITE the report period "
                             "(0x8056). Goodix: period is 5+N ms")
    parser.add_argument("--vary-width", action="store_true",
                        help="with --probe-home-press: alternate the card's "
                             "WIDTH instead of the number of draws, so the "
                             "flush-strip pitch can be read off the panel")
    parser.add_argument("--single-draw-buffer", action="store_true",
                        help="with --probe-home-press: bring the display up "
                             "with ONE LVGL draw buffer instead of the pair")
    parser.add_argument("--invalidate", type=int, default=0,
                        help="with --probe-striping: invalidate the active "
                             "screen N times after each load")
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
    # The glyph check walks imports from main.py to learn which modules the
    # product actually draws with, and clean_board has just deleted main.py.
    # Left alone the walk starts nowhere, reaches zero modules and passes over
    # an empty set -- it reported "0 modules reachable" and PASSED before this
    # existed. A copy under a name MicroPython will not auto-run gives the walk
    # its root back without giving the board a second boot script.
    stashed = mpremote(port, "cp", os.path.join(DEVICE, "main.py"),
                       ":main_src.py") == 0
    if not stashed:
        print("!! could not stash main.py; the glyph scan will report that it "
              "could not see the product rather than passing over nothing")

    rc = 1
    try:
        rc = _run_suite(port, args)
    finally:
        if stashed:
            mpremote(port, "rm", ":main_src.py")
        restored = args.keep_repl or restore_main(port, DEVICE)
    return rc if restored else 1


if __name__ == "__main__":
    sys.exit(main())
