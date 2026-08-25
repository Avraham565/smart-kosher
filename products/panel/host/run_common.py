"""Host-side helpers shared by the run_hwtest* launchers.

Runs on the developer's machine, never on the panel -- it shells out to
mpremote and talks to pyserial, neither of which exists on the device. Kept
apart from dev_common.py for exactly that reason: that one is deployed.

Each launcher used to carry its own byte-identical copy of find_panel() and
mpremote(), which is three places to edit the day the bench rig changes its
USB bridge.

restore_main() and run_on_device() are here for a sharper version of the same
reason. Every launcher deletes main.py (via clean_board) before it can touch the
board, so every launcher owes it back on every path out -- and all three had the
same hole, restoring on the success path only. One copy of that obligation is
one place to get it right.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

# The CrowPanel's USB bridge. It renumbers itself between COM7 and COM8 across
# reboots, which is why nothing here hardcodes a port.
CH340_VID_PID = (0x1A86, 0x7522)


def find_panel():
    """The panel's COM port, or None when it is not plugged in."""
    from serial.tools import list_ports
    for port in sorted(list_ports.comports(), key=lambda p: p.device):
        if (port.vid, port.pid) == CH340_VID_PID:
            return port.device
    return None


def mpremote(port, *args, **kwargs):
    """Run one mpremote command against ``port``.

    Returns the exit code, or -- with ``capture=True`` -- the finished
    CompletedProcess, for a caller that needs to read what the device printed.

    ``timeout=<seconds>`` bounds the wait and raises
    ``subprocess.TimeoutExpired`` (having killed mpremote) if the board goes
    quiet. Worth passing on anything that *runs* code: mpremote drives the raw
    REPL and waits for a terminator, so a board that resets mid-run -- a crash,
    a boot loop -- never sends one and mpremote waits for it forever, holding
    the COM port open against the next attempt.
    """
    cmd = [sys.executable, "-m", "mpremote", "connect", port] + list(args)
    timeout = kwargs.get("timeout")
    if kwargs.get("capture"):
        return subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace",
                              timeout=timeout)
    return subprocess.call(cmd, timeout=timeout)


def sync_core(port, root):
    """Copy src/smart_kosher onto the board at /lib, as a directory.

    Every suite here runs against the brain, and until now no launcher
    refreshed it. The UI suite refreshed three files out of the data package
    and nothing else, so a suite that had grown a new core dependency ran
    against whatever the board was carrying -- which is how a run reported
    ImportError on a constant that exists in the repo.

    A directory rather than a list, deliberately. Two hand-maintained payloads
    produced two false greens in one day: the UI suite's module list was
    missing fourteen names, and the brain was missing entirely. deploy.ps1
    reached this conclusion first and says why -- "The payload is the
    directory, not a list" -- and following a decision already made in this
    repo beats inventing a cleverer one beside it.

    It costs about 21 seconds, every run, and that is measured rather than
    guessed: three consecutive calls against a board where nothing had changed
    took 20.9s, 20.7s and 20.9s. mpremote skips writing a file whose content
    already matches, but it still walks and compares the whole package, so
    "unchanged" is nearly as expensive as changed. An earlier draft of this
    docstring claimed the steady state was close to free; it is not.

    That is the price and it was paid deliberately. Syncing only the files a
    suite imports would need a second closure, crossing from the flat board
    namespace into smart_kosher.*, added to a mechanism that produced two false
    greens in one day. Caching a "board already matches" marker on the host is
    worse still: deploy.ps1 and any second checkout also write /lib, so the
    marker would be a guess about the board derived from this machine, and a
    wrong one is exactly the stale-copy failure being closed here.

    Staged without __pycache__: MicroPython ignores CPython .pyc, so shipping
    them only wastes flash.
    """
    source = os.path.join(root, "src", "smart_kosher")
    stage = tempfile.mkdtemp(prefix="sk_core_")
    try:
        shutil.copytree(source, os.path.join(stage, "smart_kosher"),
                        ignore=shutil.ignore_patterns("__pycache__"))
        mpremote(port, "mkdir", ":/lib")        # already there: not an error
        return mpremote(port, "cp", "-r",
                        os.path.join(stage, "smart_kosher"), ":/lib/") == 0
    finally:
        shutil.rmtree(stage, ignore_errors=True)


# How long to listen to the console after a run went quiet, for the reason.
CONSOLE_CAPTURE_S = 4.0


def capture_console(port, seconds=CONSOLE_CAPTURE_S):
    """Print whatever the board is saying now.

    A crashed panel is not silent -- it boot-loops, and the ROM prints the panic
    and its backtrace on every cycle. That output is what names the fault
    (LoadProhibited, a Guru Meditation, a failed mount), and mpremote's raw REPL
    swallows all of it. So when a run times out, read the port directly.
    """
    import serial  # host-only, like find_panel's list_ports

    print("== what the board is saying (%.0fs) ==" % seconds)
    time.sleep(0.5)     # let Windows release the handle the killed mpremote held
    heard = b""
    try:
        with serial.Serial(port, 115200, timeout=0.2) as ser:
            deadline = time.time() + seconds
            while time.time() < deadline:
                heard += ser.read(ser.in_waiting or 1)
    except Exception as exc:
        print("(could not open {}: {})".format(port, exc))
        return
    text = heard.decode("utf-8", "replace").strip()
    print(text if text else "(silent -- it is not even rebooting)")


def run_on_device(port, code, timeout, capture=False, hint=None):
    """Run one snippet on the board, bounded.

    Returns what mpremote returned (the exit code, or the CompletedProcess with
    ``capture=True``), or ``None`` if the board went quiet -- having said so and
    dumped the console. ``hint`` is one line of context printed first, e.g. how
    to read the output that did arrive.

    Unbounded, mpremote waits on the raw REPL for a terminator a reset board
    never sends, so a board that crashes mid-run hangs the launcher forever --
    and the restore the caller had planned never runs. That is how a hardware
    test ends with a dark panel.
    """
    try:
        return mpremote(port, "exec", code, timeout=timeout, capture=capture)
    except subprocess.TimeoutExpired:
        print()
        print("!! the board went quiet after {}s -- it did not finish."
              .format(timeout))
        if hint:
            print("   " + hint)
        capture_console(port)
        return None


def _board_file_size(port, name):
    """Bytes ``name`` occupies on the board, or None if it is not there.

    The listing is the only thing that knows: mpremote reports a successful
    copy from the host side, and the host side is not where the file landed.
    """
    result = mpremote(port, "fs", "ls", ":", capture=True)
    if result is None or getattr(result, "returncode", 1) != 0:
        return None
    for line in (result.stdout or "").splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1] == name:
            try:
                return int(parts[0])
            except ValueError:
                return None
    return None


SUITE_RESULT = "HWTEST_RESULT"


def suite_verdict(lines):
    """0 if the suite said it passed, 1 for anything else -- silence included.

    mpremote does not carry the device's exit code back to the host. Measured
    on 1.28.0: `exec "raise SystemExit(1)"` and `exec "raise SystemExit(0)"`
    both return 0. So a suite scored with SystemExit exits 0 whether it passed
    or failed, and every gate built on it is decorative. The whole of this
    session's hardware verification -- 88 checks and their mutations -- was
    ultimately a person reading stdout.

    The verdict therefore comes from what the suite SAID, on a line it prints
    exactly once. The rule that makes it safe is that no line is a failure: a
    board that crashed, hung, or was reset mid-run never printed one, and
    "nothing said" must never read as "nothing wrong". Two lines is also a
    failure -- it means the output is not what we think it is.
    """
    marks = [line.strip() for line in lines
             if line.strip().startswith(SUITE_RESULT)]
    if not marks:
        print("!! the suite never reported a result -- treating that as a "
              "failure. The board stopped before the end of the run.")
        return 1
    if len(marks) > 1:
        print("!! the suite reported {} results; expected one".format(
            len(marks)))
        return 1
    parts = marks[0].split()
    if len(parts) >= 2 and parts[1] == "pass":
        return 0
    print("!! the suite reported: {}".format(marks[0]))
    return 1


def run_suite_on_device(port, code, timeout, hint=None):
    """Run a board suite, streaming its output, and return the lines it printed.

    Streamed rather than captured because these runs take minutes and the last
    line before a hang is the whole diagnosis. Collected as well, because the
    caller has to read the verdict out of it -- see suite_verdict.
    """
    cmd = [sys.executable, "-m", "mpremote", "connect", port, "exec", code]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8", errors="replace")
    lines = []

    def pump():
        for line in proc.stdout:
            line = line.rstrip()
            lines.append(line)
            print(line)

    reader = threading.Thread(target=pump)
    reader.daemon = True
    reader.start()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        print("!! no answer from the board after {}s -- killed".format(timeout))
        if hint:
            print("   " + hint)
    reader.join(5)
    return lines


def restore_main(port, device_dir):
    """Put main.py back on the panel. True if it will boot rendering again.

    A full copy, not a reset: clean_board.py DELETED main.py to get a DMA-free
    REPL, so a reset alone boots the board to a bare prompt and the screen stays
    black. This step was once a reset with no copy, and the only symptom was a
    dead panel long after the run reported success.

    Call it from a ``finally``. Everything between clean_board and here can
    fail, and the failures are the runs that most need the screen back.
    """
    source = os.path.join(device_dir, "main.py")
    want = os.path.getsize(source)
    print("== restoring main.py ==")

    # Verified by size read back from the board, not by the copy's exit code.
    # A board that is rebooting -- which is the state a crashed run leaves it
    # in, and crashed runs are exactly when this matters -- has twice taken a
    # copy and ended up with main.py at ZERO bytes. Zero bytes boots to a bare
    # REPL and a black screen, and looks identical to no main.py at all, so
    # every symptom of the failure is downstream and silent.
    for attempt in (1, 2):
        if mpremote(port, "cp", source, ":main.py") != 0:
            print("!! copy of main.py failed (attempt {})".format(attempt))
            continue
        got = _board_file_size(port, "main.py")
        if got == want:
            mpremote(port, "reset")
            print("screen is coming back")
            return True
        print("!! main.py is {} bytes on the board, expected {} "
              "(attempt {})".format(got, want, attempt))

    print("!! could not restore main.py -- the panel will boot to the "
          "REPL with a black screen. Re-run:")
    print("   python -m mpremote connect {} cp "
          "products/panel/device/main.py :main.py".format(port))
    return False
