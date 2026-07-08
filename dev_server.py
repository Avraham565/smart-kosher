"""Development server — runs the JSON API locally on http://localhost:5004

Usage:
    $env:PYTHONPATH = "src"
    python dev_server.py

All data lives in memory only (resets on restart).
Switch STORAGE = "json" to persist to ./dev_data/ between runs.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from smart_kosher.adapters import H2Simulator, MemoryEventJournal, MemoryRepository
from smart_kosher.adapters.json_repository import JsonRepository
from smart_kosher.application.control_service import ControlService
from smart_kosher.application.crud_service import CrudService
from smart_kosher.application.executor import Executor
from smart_kosher.web.server import create_app
from smart_kosher.web.settings_store import SettingsStore

# ── Storage mode ──────────────────────────────────────────────────────────────
# "memory" → in-memory only (resets on restart, good for quick UI testing)
# "json"   → persists to ./dev_data/*.json  (survives restart)

STORAGE = "json"
JSON_DIR = os.path.join(os.path.dirname(__file__), "dev_data")


def build_repository():
    if STORAGE == "json":
        os.makedirs(JSON_DIR, exist_ok=True)
        return JsonRepository(JSON_DIR)
    return MemoryRepository()


def main():
    repo     = build_repository()
    gateway  = H2Simulator()          # always ACKs — simulates Zigbee coordinator
    journal  = MemoryEventJournal()
    executor = Executor(gateway, journal)
    crud     = CrudService(repo)
    control  = ControlService(executor, repo)
    settings = SettingsStore(
        os.path.join(JSON_DIR if STORAGE == "json" else ".", "settings.json"),
        defaults={
            "city": "ירושלים",
            "lat": 31.7683,
            "lon": 35.2137,
            "utc_offset_minutes": 120,
            "candle_offset": 18,
            "tzais_offset": 40,
        },
    )

    def status_info():
        return {
            "gateway": "simulator",
            "storage": STORAGE,
            "commands_sent": len(gateway.commands),
        }

    app = create_app(crud, control, settings, repo, status_info)

    print()
    print("  Smart Kosher dev server")
    print("  -----------------------")
    print("  API: http://localhost:5004/api/zones")
    print("       http://localhost:5004/api/endpoints")
    print("       http://localhost:5004/api/groups")
    print("       http://localhost:5004/api/schedules")
    print("       http://localhost:5004/api/settings")
    print()

    app.run(host="0.0.0.0", port=5004, debug=True)


if __name__ == "__main__":
    main()
