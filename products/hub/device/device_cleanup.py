"""Runs ON the device via `mpremote run` — removes the old package tree.

Needed because a deploy may switch between .py and .mpy formats; stale
files of the other format would shadow the fresh ones on import.
"""

import os


def rmtree(path):
    try:
        stat = os.stat(path)
    except OSError:
        return
    if stat[0] & 0x4000:  # directory
        for name in os.listdir(path):
            rmtree(path + "/" + name)
        os.rmdir(path)
    else:
        os.remove(path)


rmtree("/lib/smart_kosher")
print("removed /lib/smart_kosher")
