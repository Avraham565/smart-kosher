"""Persistent key-value store for runtime settings (city, UTC offset)."""

try:
    import ujson as json
except ImportError:
    import json


class SettingsStore:
    def __init__(self, path, defaults=None):
        self._path = path
        self._data = dict(defaults or {})
        self._data.update(self._load())

    def get(self):
        return dict(self._data)

    def update(self, patch):
        self._data.update(patch)
        self._save()

    def _load(self):
        try:
            with open(self._path) as f:
                return json.loads(f.read())
        except Exception:
            return {}

    def _save(self):
        with open(self._path, "w") as f:
            f.write(json.dumps(self._data))
