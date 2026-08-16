"""One contract, two implementations -- asserted against both.

MemoryRepository and JsonRepository implement the same port, and 79% of the
smaller one appears verbatim in the larger. The split that made this dangerous
is which one each caller gets: every route/api/serial/web suite builds its
fixtures on MemoryRepository, while both products run JsonRepository. A
behaviour that differs between them is therefore invisible -- the suite is
green and the device is not.

That was not hypothetical. JsonRepository.upsert caught the domain's
XValidationError(ValueError) and re-raised it as RepositoryValidationError,
which did not inherit ValueError; Api.dispatch classifies ValueError as
bad_request and everything else as internal. So every rejected field answered
500 "internal error" on both products, while these suites saw 400 and passed.

The API-level half of this file is the part that would have caught it: the
same request, the same expected status, once per implementation.
"""

import asyncio
import os
import shutil
import tempfile
import unittest

from microdot.test_client import TestClient

from smart_kosher.adapters import (
    H2Simulator,
    JsonRepository,
    MemoryEventJournal,
    MemoryRepository,
    SettingsStore,
)
from smart_kosher.adapters.json_repository import (
    RepositoryCorruptionError,
    RepositoryValidationError,
)
from smart_kosher.application.control_service import ControlService
from smart_kosher.application.crud_service import CrudService
from smart_kosher.application.executor import Executor
from smart_kosher.web.server import create_app

_SCHEDULE = {
    "name": "תזמון", "enabled": True,
    "target_type": "endpoint", "target_id": "ep_1",
    "trigger_type": "fixed_time", "trigger_data": {"h": 20, "m": 0},
    "recurrence_type": "daily", "recurrence_data": {}, "action_type": "on",
}


class RepositoryContractTests(unittest.TestCase):
    """Both implementations, the same assertions."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sk_contract_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _implementations(self):
        yield "memory", MemoryRepository()
        yield "json", JsonRepository(os.path.join(self.tmp, "data"))

    def _client(self, repo, tag):
        executor = Executor(H2Simulator(["sent_to_zigbee"]), MemoryEventJournal())
        settings = SettingsStore(
            os.path.join(self.tmp, "settings_{}.json".format(tag)),
            defaults={"city": "ירושלים", "lat": 31.7683, "lon": 35.2137,
                      "utc_offset_minutes": 120},
        )
        return TestClient(create_app(
            CrudService(repo), ControlService(executor, repo), settings, repo,
            collect_after_request=False,
        ))

    # ── the contract itself ───────────────────────────────────────────────

    def test_invalid_input_raises_a_valueerror_in_both(self):
        # Api.dispatch keys bad_request off ValueError. An implementation that
        # rejects input with anything else turns a user's typo into a 500.
        for tag, repo in self._implementations():
            with self.subTest(implementation=tag):
                with self.assertRaises(ValueError):
                    repo.upsert("zones", {"id": "z_1", "name": ""})
                with self.assertRaises(ValueError):
                    repo.get_all("widgets")

    def test_revision_advances_on_mutation_in_both(self):
        # The absolute value is an implementation detail (the two do not start
        # from the same base); Planner only ever compares it for change.
        for tag, repo in self._implementations():
            with self.subTest(implementation=tag):
                before = repo.get_revision("zones")
                repo.replace_all("zones", [{"id": "z_1", "name": "סלון"}])
                self.assertNotEqual(before, repo.get_revision("zones"))

    def test_round_trip_is_identical_in_both(self):
        for tag, repo in self._implementations():
            with self.subTest(implementation=tag):
                self.assertEqual([], repo.get_all("zones"))
                self.assertIsNone(repo.get_by_id("zones", "z_missing"))
                repo.upsert("zones", {"id": "z_1", "name": "סלון"})
                self.assertEqual("סלון", repo.get_by_id("zones", "z_1")["name"])
                repo.delete_by_id("zones", "z_1")
                self.assertEqual([], repo.get_all("zones"))

    def test_corruption_is_not_a_valueerror(self):
        # The mirror image of the bug: bad *storage* is an internal fault and
        # must stay a 500, so it must not be swept into the bad_request arm.
        self.assertFalse(issubclass(RepositoryCorruptionError, ValueError))
        self.assertTrue(issubclass(RepositoryValidationError, ValueError))

    # ── the same request, once per implementation ─────────────────────────

    def _assert_same_status(self, expected, call):
        async def go():
            seen = {}
            for tag, repo in self._implementations():
                res = await call(self._client(repo, tag))
                seen[tag] = res.status_code
            for tag, status in seen.items():
                with self.subTest(implementation=tag):
                    self.assertEqual(expected, status)
            self.assertEqual(1, len(set(seen.values())),
                             "implementations disagree: {}".format(seen))
        asyncio.run(go())

    def test_missing_name_is_bad_request_in_both(self):
        self._assert_same_status(400, lambda c: c.post("/api/zones", body={}))

    def test_empty_name_is_bad_request_in_both(self):
        self._assert_same_status(
            400, lambda c: c.post("/api/zones", body={"name": ""}))

    def test_wrong_type_name_is_bad_request_in_both(self):
        self._assert_same_status(
            400, lambda c: c.post("/api/zones", body={"name": 123}))

    def test_unknown_recurrence_is_bad_request_in_both(self):
        body = dict(_SCHEDULE, recurrence_type="weekly")
        self._assert_same_status(
            400, lambda c: c.post("/api/schedules", body=body))

    def test_toggle_schedule_is_bad_request_in_both(self):
        # toggle is manual-control only (CLAUDE.md); it must be refused the
        # same way whichever repository is underneath.
        body = dict(_SCHEDULE, action_type="toggle")
        self._assert_same_status(
            400, lambda c: c.post("/api/schedules", body=body))

    def test_valid_create_succeeds_in_both(self):
        self._assert_same_status(
            201, lambda c: c.post("/api/zones", body={"name": "סלון"}))


if __name__ == "__main__":
    unittest.main()
