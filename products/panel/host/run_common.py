"""Host-side helpers shared by the run_hwtest* launchers.

Runs on the developer's machine, never on the panel -- it shells out to
mpremote and talks to pyserial, neither of which exists on the device. Kept
apart from dev_common.py for exactly that reason: that one is deployed.

Each launcher used to carry its own byte-identical copy of find_panel() and
mpremote(), which is three places to edit the day the bench rig changes its
USB bridge.
"""

import subprocess
import sys

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
    """
    cmd = [sys.executable, "-m", "mpremote", "connect", port] + list(args)
    if kwargs.get("capture"):
        return subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
    return subprocess.call(cmd)
