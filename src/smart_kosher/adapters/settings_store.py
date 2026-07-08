"""Persistent key-value store for runtime settings (city, UTC offset).

Writes follow the same durability contract as the JSON repository:
the new content goes to a temporary file first, the previous file is
kept as a backup, and startup recovers from the temporary or backup
file when the primary is missing or unreadable.
"""

try:
    import ujson as json
except ImportError:
    import json

import os


def _exists(path):
    try:
        os.stat(path)
        return True
    except OSError:
        return False


def _replace(source, destination):
    replace = getattr(os, "replace", None)
    if replace is not None:
        replace(source, destination)
        return
    if _exists(destination):
        os.remove(destination)
    os.rename(source, destination)


def _flush_file(handle):
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


def _sync_filesystem():
    sync = getattr(os, "sync", None)
    if sync is not None:
        sync()


class SettingsStore:
    def __init__(self, path, defaults=None):
        self._path = path
        self._data = dict(defaults or {})
        self.load_error = None
        self._data.update(self._load())

    def get(self):
        return dict(self._data)

    def update(self, patch):
        merged = dict(self._data)
        merged.update(patch)
        self._save(merged)
        self._data = merged

    def _read(self, path):
        with open(path) as handle:
            data = json.loads(handle.read())
        if not isinstance(data, dict):
            raise ValueError("settings file must contain a JSON object")
        return data

    def _load(self):
        temporary = self._path + ".tmp"
        backup = self._path + ".bak"
        candidates = (self._path, temporary, backup)
        if not any(_exists(path) for path in candidates):
            return {}

        errors = []
        for path in candidates:
            try:
                data = self._read(path)
                if path != self._path:
                    _replace(path, self._path)
                    _sync_filesystem()
                return data
            except (OSError, ValueError) as exc:
                errors.append(str(exc))
        # Never silently discard a corrupt file: keep it for inspection,
        # fall back to defaults, and expose the failure to the caller.
        self.load_error = "; ".join(errors)
        return {}

    def _save(self, data):
        temporary = self._path + ".tmp"
        backup = self._path + ".bak"
        with open(temporary, "w") as handle:
            handle.write(json.dumps(data))
            _flush_file(handle)

        if _exists(self._path):
            _replace(self._path, backup)
        try:
            _replace(temporary, self._path)
            _sync_filesystem()
        except OSError:
            if _exists(backup) and not _exists(self._path):
                _replace(backup, self._path)
            raise
