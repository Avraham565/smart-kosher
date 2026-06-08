import json
import os
import shutil
import unittest

from smart_kosher.adapters.json_repository import (
    JsonEventJournal,
    JsonRepository,
    RepositoryCorruptionError,
    RepositoryValidationError,
)


class JsonRepositoryTests(unittest.TestCase):
    base = os.path.join("tests", ".tmp-storage")

    def setUp(self):
        if os.path.exists(self.base):
            shutil.rmtree(self.base)
        self.repository = JsonRepository(self.base)

    def tearDown(self):
        if os.path.exists(self.base):
            shutil.rmtree(self.base)

    def test_crud_revisions_and_defensive_copies(self):
        initial_revision = self.repository.get_revision("zones")
        entity = {"id": "one", "name": "Kitchen"}
        self.assertEqual("created", self.repository.upsert("zones", entity))
        self.assertGreater(self.repository.get_revision("zones"), initial_revision)
        loaded = self.repository.get_by_id("zones", "one")
        loaded["name"] = "Changed outside"
        self.assertEqual("Kitchen", self.repository.get_by_id("zones", "one")["name"])
        self.assertEqual(
            "updated",
            self.repository.upsert("zones", {"id": "one", "name": "Updated"}),
        )
        self.assertTrue(self.repository.delete_by_id("zones", "one"))
        self.assertFalse(self.repository.delete_by_id("zones", "one"))

    def test_invalid_entities_are_rejected(self):
        with self.assertRaises(RepositoryValidationError):
            self.repository.upsert("zones", {"name": "missing id"})
        with self.assertRaises(RepositoryValidationError):
            self.repository.get_all("unknown")

    def test_instances_are_isolated(self):
        second_base = os.path.join("tests", ".tmp-storage-second")
        try:
            if os.path.exists(second_base):
                shutil.rmtree(second_base)
            second = JsonRepository(second_base)
            self.repository.upsert("zones", {"id": "one", "name": "Kitchen"})
            self.assertEqual([], second.get_all("zones"))
        finally:
            if os.path.exists(second_base):
                shutil.rmtree(second_base)

    def test_corrupt_primary_recovers_from_backup(self):
        self.repository.upsert("zones", {"id": "one", "name": "Version 1"})
        self.repository.upsert("zones", {"id": "one", "name": "Version 2"})
        primary = os.path.join(self.base, "zones.json")
        with open(primary, "w") as handle:
            handle.write("{broken")

        recovered = JsonRepository(self.base)
        self.assertEqual("Version 1", recovered.get_by_id("zones", "one")["name"])
        with open(primary) as handle:
            self.assertEqual("Version 1", json.load(handle)[0]["name"])

    def test_interrupted_first_save_recovers_temporary_file(self):
        temporary = os.path.join(self.base, "zones.json.tmp")
        with open(temporary, "w") as handle:
            json.dump([{"id": "one", "name": "Kitchen"}], handle)
        recovered = JsonRepository(self.base)
        self.assertEqual("one", recovered.get_all("zones")[0]["id"])
        self.assertTrue(os.path.exists(os.path.join(self.base, "zones.json")))

    def test_corrupt_primary_and_backup_raise(self):
        for suffix in ("", ".bak"):
            with open(os.path.join(self.base, "zones.json" + suffix), "w") as handle:
                handle.write("{broken")
        with self.assertRaises(RepositoryCorruptionError):
            JsonRepository(self.base)

    def test_duplicate_ids_in_file_raise(self):
        path = os.path.join(self.base, "zones.json")
        with open(path, "w") as handle:
            json.dump([
                {"id": "x", "name": "One"},
                {"id": "x", "name": "Two"},
            ], handle)
        with self.assertRaises(RepositoryCorruptionError):
            JsonRepository(self.base)

    def test_json_event_journal_survives_repository_reload(self):
        journal = JsonEventJournal(self.repository)
        event = {
            "event_id": "event-1",
            "schedule_id": "schedule-1",
            "source_date": (2026, 6, 8),
            "utc_minute": 100,
            "target_type": "group",
            "target_id": "all",
            "action_type": "on",
            "action_data": {},
        }
        journal.record(event, {"status": "executed", "attempts": 1})
        reloaded = JsonEventJournal(JsonRepository(self.base))
        self.assertTrue(reloaded.was_executed("event-1"))
        self.assertEqual((2026, 6, 8), reloaded.get("event-1")["event"]["source_date"])
        self.assertTrue(os.path.exists(os.path.join(self.base, "journal.log")))

    def test_json_event_journal_is_bounded(self):
        journal = JsonEventJournal(self.repository, max_records=2)
        for index in range(3):
            journal.record({
                "event_id": "event-{}".format(index),
                "schedule_id": "schedule-1",
                "source_date": (2026, 6, 8),
                "utc_minute": 100 + index,
                "target_type": "group",
                "target_id": "all",
                "action_type": "on",
                "action_data": {},
            }, {"status": "executed", "attempts": 1})
        self.assertFalse(journal.was_executed("event-0"))
        self.assertTrue(journal.was_executed("event-2"))
        self.assertIsNone(journal.get("event-0"))
        self.assertIsNotNone(journal.get("event-1"))
        self.assertIsNotNone(journal.get("event-2"))
        self.assertEqual(2, len(self.repository.get_all("journal")))

        reloaded_repository = JsonRepository(self.base)
        reloaded = JsonEventJournal(reloaded_repository, max_records=2)
        self.assertFalse(reloaded.was_executed("event-0"))
        self.assertTrue(reloaded.was_executed("event-2"))
        self.assertEqual(2, len(reloaded_repository.get_all("journal")))

    def test_json_event_journal_migrates_legacy_repository_records(self):
        event = {
            "event_id": "event-legacy",
            "schedule_id": "schedule-1",
            "source_date": (2026, 6, 8),
            "utc_minute": 100,
            "target_type": "group",
            "target_id": "all",
            "action_type": "on",
            "action_data": {},
        }
        self.repository.replace_all("journal", [{
            "id": event["event_id"],
            "event": event,
            "result": {"status": "executed", "attempts": 1},
        }])

        journal = JsonEventJournal(self.repository)
        self.assertTrue(journal.was_executed("event-legacy"))
        journal.record({
            **event,
            "event_id": "event-new",
            "utc_minute": 101,
        }, {"status": "executed", "attempts": 1})
        with open(os.path.join(self.base, "journal.json"), "w") as handle:
            handle.write("{obsolete legacy data")

        reloaded = JsonEventJournal(JsonRepository(self.base))
        self.assertTrue(reloaded.was_executed("event-legacy"))
        self.assertTrue(reloaded.was_executed("event-new"))

    def test_json_event_journal_recovers_from_truncated_last_record(self):
        journal = JsonEventJournal(self.repository, max_records=2)
        event = {
            "event_id": "event-1",
            "schedule_id": "schedule-1",
            "source_date": (2026, 6, 8),
            "utc_minute": 100,
            "target_type": "group",
            "target_id": "all",
            "action_type": "on",
            "action_data": {},
        }
        journal.record(event, {"status": "executed", "attempts": 1})
        with open(os.path.join(self.base, "journal.log"), "a") as handle:
            handle.write("{partial")

        recovered = JsonEventJournal(JsonRepository(self.base), max_records=2)
        self.assertTrue(recovered.was_executed("event-1"))
        recovered.record({
            **event,
            "event_id": "event-2",
            "utc_minute": 101,
        }, {"status": "executed", "attempts": 1})
        reloaded = JsonEventJournal(JsonRepository(self.base), max_records=2)
        self.assertTrue(reloaded.was_executed("event-1"))
        self.assertTrue(reloaded.was_executed("event-2"))


if __name__ == "__main__":
    unittest.main()
