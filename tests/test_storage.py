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

    def test_every_journal_append_is_synced_to_the_medium(self):
        """Not the first one only, which is what the code used to do.

        On MicroPython _flush_file is a no-op -- it returns early when os.fsync
        is absent -- so os.sync() is the only call that reaches the flash. The
        old code made it conditional on the log file having just been created,
        so every append after the very first one on that device stayed in the
        cache. An event fires, the power goes, and the next boot reads a
        journal missing it: was_executed() says no, and the catch-up switches
        the relay again.

        Counted by patching the module's own sync, because there is nothing
        else to observe. On this host os.sync does not exist at all, so the
        durable and the broken versions produce byte-identical files -- which
        is precisely why the bug survived a green suite.
        """
        from smart_kosher.adapters import json_repository as module

        journal = JsonEventJournal(self.repository)
        calls = []
        original = module._sync_filesystem
        module._sync_filesystem = lambda: calls.append(1)
        try:
            for index in range(3):
                journal.record(
                    {"event_id": "sync-{}".format(index),
                     "schedule_id": "s", "source_date": (2026, 6, 8),
                     "utc_minute": 100 + index, "target_type": "group",
                     "target_id": "all", "action_type": "on",
                     "action_data": {}},
                    {"status": "executed", "attempts": 1})
        finally:
            module._sync_filesystem = original

        self.assertEqual(3, len(calls),
                         "an append that is not synced is not journalled")

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

    # ── the read path: an unreadable log must not read as an empty one ──

    def _event(self, index):
        return {"event_id": "event-{}".format(index), "schedule_id": "s",
                "source_date": (2026, 6, 8), "utc_minute": 100 + index,
                "target_type": "group", "target_id": "all",
                "action_type": "on", "action_data": {}}

    def _log(self, suffix=""):
        return os.path.join(self.base, "journal.log" + suffix)

    def _journal_with(self, count, max_records=128):
        journal = JsonEventJournal(self.repository, max_records=max_records)
        for index in range(count):
            journal.record(self._event(index),
                           {"status": "executed", "attempts": 1})
        return journal

    def test_an_emptied_primary_log_recovers_from_the_backup(self):
        """A zero-length primary is not proof that nothing ever fired.

        It is also what a write cut short leaves behind, and it reads back
        without error -- _read_log returns ([], False) quite happily. So the
        primary always won and .tmp and .bak were never opened, even though
        compaction writes a .bak every single time.

        The cost is the whole point of the journal: every event looks
        un-executed, and the boot catch-up fires all of them again.

        Five records with max_records=2, because compaction triggers at
        physical + 1 > max_records * 2 and the .bak this depends on does not
        exist before the fifth. Measured rather than assumed, because the
        arrangement is not obvious: after the fifth the primary holds
        [event-3, event-4] and the backup holds [event-0 .. event-3]. The
        backup is the log as it stood *before* compaction, so event-4 was
        written after it and is not in it.

        So the assertion is event-3, the newest the backup can honestly
        provide. Recovering from a backup always loses whatever was written
        after it -- and losing one is what this trades against losing all five.
        """
        self._journal_with(5, max_records=2)
        self.assertTrue(os.path.exists(self._log(".bak")),
                        "no backup was written, so nothing here is proven")
        open(self._log(), "w").close()                # truncated to nothing

        recovered = JsonEventJournal(JsonRepository(self.base), max_records=2)
        self.assertTrue(recovered.was_executed("event-3"),
                        "an emptied log re-fired every event in it")

    def test_a_genuinely_empty_log_is_not_treated_as_corruption(self):
        # The other half: nothing has fired yet, or compaction emptied it. That
        # must stay silent, or every fresh device reports a corrupt journal.
        open(self._log(), "w").close()
        journal = JsonEventJournal(JsonRepository(self.base))
        self.assertFalse(journal.was_executed("event-0"))

    def test_an_undecodable_primary_log_falls_through_to_the_backup(self):
        """readlines() raises UnicodeDecodeError on a torn multi-byte char.

        UnicodeDecodeError is a ValueError, and _load_log caught only OSError
        and RepositoryCorruptionError -- so it escaped the loop and took
        startup down before the backup was tried. A recovery path that existed
        and could not be reached.
        """
        self._journal_with(5, max_records=2)
        with open(self._log(), "wb") as handle:
            handle.write(b'{"id": "\xff\xfe broken utf-8"}\n')

        recovered = JsonEventJournal(JsonRepository(self.base), max_records=2)
        self.assertTrue(recovered.was_executed("event-3"))

    def test_no_readable_copy_at_all_still_raises(self):
        # Recovering further must not become "never complain": storage that is
        # gone in every copy is an internal fault, and 500 is the right answer.
        self._journal_with(5, max_records=2)
        for suffix in ("", ".tmp", ".bak"):
            if os.path.exists(self._log(suffix)):
                with open(self._log(suffix), "w") as handle:
                    handle.write('{"not": "a record"}\nand junk\n')
        with self.assertRaises(RepositoryCorruptionError):
            JsonEventJournal(JsonRepository(self.base), max_records=2)


class SettingsStoreTests(unittest.TestCase):
    base = os.path.join("tests", ".tmp-settings")

    def setUp(self):
        if os.path.exists(self.base):
            shutil.rmtree(self.base)
        os.makedirs(self.base)
        self.path = os.path.join(self.base, "settings.json")

    def tearDown(self):
        if os.path.exists(self.base):
            shutil.rmtree(self.base)

    def _store(self, defaults=None):
        from smart_kosher.adapters.settings_store import SettingsStore
        return SettingsStore(self.path, defaults=defaults)

    def test_defaults_when_no_file(self):
        store = self._store({"city": "ירושלים"})
        self.assertEqual("ירושלים", store.get()["city"])
        self.assertIsNone(store.load_error)

    def test_update_persists_and_keeps_backup(self):
        store = self._store({"city": "ירושלים"})
        store.update({"lat": 32.0})
        store.update({"lon": 34.0})
        self.assertTrue(os.path.exists(self.path))
        self.assertTrue(os.path.exists(self.path + ".bak"))
        reloaded = self._store()
        self.assertEqual(32.0, reloaded.get()["lat"])
        self.assertEqual(34.0, reloaded.get()["lon"])

    def test_corrupt_primary_recovers_from_backup(self):
        store = self._store()
        store.update({"city": "צפת"})
        store.update({"city": "חיפה"})  # primary=חיפה, backup=צפת
        with open(self.path, "w") as handle:
            handle.write("{corrupt")
        recovered = self._store()
        self.assertEqual("צפת", recovered.get()["city"])
        self.assertIsNone(recovered.load_error)

    def test_all_corrupt_reports_load_error(self):
        with open(self.path, "w") as handle:
            handle.write("{corrupt")
        store = self._store({"city": "ירושלים"})
        self.assertEqual("ירושלים", store.get()["city"])
        self.assertIsNotNone(store.load_error)

    def test_non_dict_content_reports_load_error(self):
        with open(self.path, "w") as handle:
            handle.write(json.dumps([1, 2, 3]))
        store = self._store()
        self.assertIsNotNone(store.load_error)


if __name__ == "__main__":
    unittest.main()
