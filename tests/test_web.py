"""Tests for CrudService, ControlService, and API routes."""

import asyncio
import unittest

from smart_kosher.adapters import H2Simulator, MemoryEventJournal, MemoryRepository
from smart_kosher.application.control_service import ControlService
from smart_kosher.application.crud_service import CrudService, NotFoundError
from smart_kosher.application.executor import Executor

# ── Helpers ───────────────────────────────────────────────────────────────────

def _repo(initial=None):
    return MemoryRepository(initial or {})


def _crud(initial=None):
    return CrudService(_repo(initial))


def _zone(name="סלון"):
    return {"name": name}


def _endpoint(name="אור", zone_id=None):
    e = {"name": name}
    if zone_id:
        e["zone_id"] = zone_id
    return e


def _group(name="קבוצה", member_ids=None):
    return {"name": name, "member_ids": member_ids or []}


def _schedule(target_id="ep_x", target_type="endpoint"):
    return {
        "name": "תזמון בדיקה",
        "enabled": True,
        "target_type": target_type,
        "target_id": target_id,
        "trigger_type": "fixed_time",
        "trigger_data": {"h": 20, "m": 0},
        "recurrence_type": "daily",
        "recurrence_data": {},
        "action_type": "on",
        "action_data": {},
    }


# ── CrudService ───────────────────────────────────────────────────────────────

class TestCrudServiceZones(unittest.TestCase):
    def test_create_and_list(self):
        svc = _crud()
        z = svc.create("zones", _zone("סלון"))
        self.assertIn("id", z)
        self.assertTrue(z["id"].startswith("z_"))
        self.assertEqual("סלון", z["name"])
        self.assertEqual(1, len(svc.list("zones")))

    def test_get_existing(self):
        svc = _crud()
        z = svc.create("zones", _zone())
        got = svc.get("zones", z["id"])
        self.assertEqual(z["id"], got["id"])

    def test_get_missing_raises(self):
        with self.assertRaises(NotFoundError):
            _crud().get("zones", "no_such_id")

    def test_update(self):
        svc = _crud()
        z = svc.create("zones", _zone("סלון"))
        updated = svc.update("zones", z["id"], {"name": "מטבח"})
        self.assertEqual("מטבח", updated["name"])
        self.assertEqual(z["id"], updated["id"])

    def test_update_missing_raises(self):
        with self.assertRaises(NotFoundError):
            _crud().update("zones", "bad_id", {"name": "x"})

    def test_delete(self):
        svc = _crud()
        z = svc.create("zones", _zone())
        svc.delete("zones", z["id"])
        self.assertEqual([], svc.list("zones"))

    def test_delete_missing_raises(self):
        with self.assertRaises(NotFoundError):
            _crud().delete("zones", "bad_id")

    def test_id_uniqueness(self):
        svc = _crud()
        ids = {svc.create("zones", _zone())["id"] for _ in range(20)}
        self.assertEqual(20, len(ids))


class TestCrudServiceEndpoints(unittest.TestCase):
    def test_create_with_optional_fields(self):
        svc = _crud()
        ep = svc.create("endpoints", {"name": "אור", "ieee_address": "0x001", "zigbee_endpoint": 1})
        self.assertTrue(ep["id"].startswith("ep_"))

    def test_create_validates_zigbee_endpoint(self):
        svc = _crud()
        with self.assertRaises(Exception):
            svc.create("endpoints", {"name": "x", "zigbee_endpoint": 300})


class TestCrudServiceSchedules(unittest.TestCase):
    def test_create_valid_schedule(self):
        svc = _crud()
        s = svc.create("schedules", _schedule())
        self.assertTrue(s["id"].startswith("sch_"))

    def test_create_invalid_schedule_raises(self):
        svc = _crud()
        with self.assertRaises(Exception):
            svc.create("schedules", {"name": "bad", "action_type": "fly"})


# ── ControlService ────────────────────────────────────────────────────────────

class TestControlService(unittest.TestCase):
    def _services(self, responses=None):
        repo     = _repo()
        gateway  = H2Simulator(responses or ["sent_to_zigbee"])
        journal  = MemoryEventJournal()
        executor = Executor(gateway, journal)
        ctrl     = ControlService(executor, repo)
        return repo, ctrl

    def test_send_to_endpoint_ack(self):
        repo, ctrl = self._services(["sent_to_zigbee"])
        ep = CrudService(repo).create("endpoints", _endpoint())
        result = asyncio.run(ctrl.send("endpoint", ep["id"], "on"))
        self.assertEqual("executed", result["status"])

    def test_send_to_group_ack(self):
        repo, ctrl = self._services(["sent_to_zigbee"])
        grp = CrudService(repo).create("groups", _group())
        result = asyncio.run(ctrl.send("group", grp["id"], "off"))
        self.assertEqual("executed", result["status"])

    def test_unknown_target_raises(self):
        _, ctrl = self._services()
        with self.assertRaises(NotFoundError):
            asyncio.run(ctrl.send("endpoint", "nonexistent", "on"))

    def test_invalid_action_raises(self):
        repo, ctrl = self._services()
        ep = CrudService(repo).create("endpoints", _endpoint())
        with self.assertRaises(ValueError):
            asyncio.run(ctrl.send("endpoint", ep["id"], "dim"))

    def test_invalid_target_type_raises(self):
        repo, ctrl = self._services()
        ep = CrudService(repo).create("endpoints", _endpoint())
        with self.assertRaises(ValueError):
            asyncio.run(ctrl.send("device", ep["id"], "on"))

    def test_timeout_then_ack_retried(self):
        repo, ctrl = self._services(["timeout", "sent_to_zigbee"])
        ep = CrudService(repo).create("endpoints", _endpoint())
        result = asyncio.run(ctrl.send("endpoint", ep["id"], "toggle"))
        self.assertEqual("executed", result["status"])
        self.assertEqual(2, result["attempts"])


if __name__ == "__main__":
    unittest.main()
