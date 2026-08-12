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

from ._atomic_io import exists as _exists
from ._atomic_io import flush_file as _flush_file
from ._atomic_io import replace as _replace
from ._atomic_io import sync_filesystem as _sync_filesystem


class SettingsStore:
    def __init__(self, path, defaults=None):
        self._path = path
        self.load_error = None
        self._stored = self._load()
        self._data = dict(defaults or {})
        self._data.update(self._stored)

    def get(self):
        """Effective settings: what is stored, over the defaults."""
        return dict(self._data)

    def stored(self):
        """Only what the file actually holds, with no defaults filled in.

        A migration needs this. ``get()`` cannot answer "was this ever set?" --
        a default is indistinguishable from a stored value there, so a device
        missing ``elevation`` reads back the default one and a backfill that
        checked ``get()`` would decide there was nothing to do.
        """
        return dict(self._stored)

    def update(self, patch):
        merged = dict(self._data)
        merged.update(patch)
        self._save(merged)
        self._data = merged
        # _save writes the merged view, so everything in it is now on disk.
        self._stored = dict(merged)

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
