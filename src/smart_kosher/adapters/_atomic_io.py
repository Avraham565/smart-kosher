"""Durable file replacement, shared by every adapter that persists JSON.

The contract: write the new content to ``path.tmp``, keep the previous file as
``path.bak``, and recover from either on the next start when the primary is
missing or unreadable. A power cut mid-write must never leave a device with no
readable settings and no readable data.

This lived twice -- byte for byte -- in ``json_repository`` and
``settings_store``, which both documented it as "the same durability
contract". Two copies of the code that exists to survive a power cut is the
worst place to keep a divergence, because the difference only shows up on the
day the power actually cuts.

Every function tolerates MicroPython's smaller ``os``: ``replace``, ``fsync``
and ``sync`` are absent there, and their absence is not an error.
"""

import os


def exists(path):
    try:
        os.stat(path)
        return True
    except OSError:
        return False


def replace(source, destination):
    """Move ``source`` onto ``destination``, atomically where the OS allows."""
    os_replace = getattr(os, "replace", None)
    if os_replace is not None:
        os_replace(source, destination)
        return
    # MicroPython: rename refuses to clobber, so clear the target first. The
    # window between the two is why the .bak copy exists.
    if exists(destination):
        os.remove(destination)
    os.rename(source, destination)


def flush_file(handle):
    """Push a written handle as far towards the medium as the platform allows."""
    flush = getattr(handle, "flush", None)
    if flush is not None:
        flush()

    fsync = getattr(os, "fsync", None)
    fileno = getattr(handle, "fileno", None)
    if fsync is None or fileno is None:
        return
    try:
        descriptor = fileno()
    except (AttributeError, OSError):
        return
    fsync(descriptor)


def sync_filesystem():
    sync = getattr(os, "sync", None)
    if sync is not None:
        sync()
