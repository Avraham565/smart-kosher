"""Development server — runs the JSON API locally on http://localhost:5004

Usage:
    $env:PYTHONPATH = "src"
    python tools/dev_server.py

Data persists to tools/dev_data/ between runs -- STORAGE is "json" below.
Switch it to "memory" for a server that resets on every restart.

Binds 127.0.0.1, like apps/desktop/server.py: this serves an unauthenticated
API over whatever network the machine is on, and a development default should
not be reachable from the rest of it.
"""

import os
import sys

# tools/ -> repo root, then src. Kept as one call with no assignment before it:
# a bare sys.path tweak may precede the imports below, a binding may not (E402).
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from smart_kosher.adapters import (
    H2Simulator,
    MemoryEventJournal,
    MemoryRepository,
    SettingsStore,
)
from smart_kosher.adapters.json_repository import JsonRepository
from smart_kosher.application.control_service import ControlService
from smart_kosher.application.crud_service import CrudService
from smart_kosher.application.executor import Executor
from smart_kosher.application.migrations import apply_all as apply_migrations
from smart_kosher.application.migrations import describe as describe_migrations
from smart_kosher.application.views import SETTINGS_DEFAULTS
from smart_kosher.web.server import create_app

# ── Storage mode ──────────────────────────────────────────────────────────────
# "memory" → in-memory only (resets on restart, good for quick UI testing)
# "json"   → persists to tools/dev_data/*.json  (survives restart)

STORAGE = "json"
JSON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dev_data")


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
    # Shared defaults, so the dev server computes the same zmanim as the real
    # products instead of its own (it had candle_offset 18 against product A's 20).
    defaults = dict(SETTINGS_DEFAULTS)
    defaults["city"] = "ירושלים"
    settings = SettingsStore(
        os.path.join(JSON_DIR if STORAGE == "json" else ".", "settings.json"),
        defaults=defaults,
    )

    for line in describe_migrations(apply_migrations(repo, settings)):
        print("  " + line)

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

    # 127.0.0.1, not 0.0.0.0. Every line above advertises localhost, and
    # this API has no authentication of any kind -- binding all
    # interfaces put it on the LAN for anyone who could reach the port.
    app.run(host="127.0.0.1", port=5004, debug=True)


if __name__ == "__main__":
    main()
