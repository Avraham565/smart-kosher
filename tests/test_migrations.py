import json
import os
import shutil
import tempfile
import unittest

from smart_kosher.adapters import JsonRepository, MemoryRepository, SettingsStore
from smart_kosher.application.migrations import apply_all, describe
from smart_kosher.application.views import SETTINGS_DEFAULTS
from smart_kosher.domain.schedules import ZMAN_KEYS, validate_schedule


def _schedule(schedule_id, zman, trigger_type="zman"):
    trigger_data = {"zman": zman}
    if trigger_type == "zman_offset":
        trigger_data["offset"] = -15
    return {
        "id": schedule_id,
        "name": "boiler",
        "target_type": "endpoint",
        "target_id": "ep1",
        "action_type": "on",
        "action_data": {},
        "trigger_type": trigger_type,
        "trigger_data": trigger_data,
        "recurrence_type": "daily",
        "recurrence_data": {},
    }


class RetiredZmanMigrationTests(unittest.TestCase):
    """A schedule on a retired zman is data no write path can produce.

    It only exists in a file written before the zman was retired, so every
    test here seeds the file directly. Seeding through the repository would
    prove nothing -- validation rejects it, which is the whole problem.
    """

    def setUp(self):
        self.data_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.data_dir, True)

    def _seed(self, *schedules):
        path = os.path.join(self.data_dir, "schedules.json")
        with open(path, "w") as handle:
            json.dump(list(schedules), handle)
        return path

    def test_a_stale_schedule_does_not_stop_the_device_from_starting(self):
        # The regression that matters most. Loading validates every record, and
        # a retired zman fails that check. If it were treated as corruption the
        # loader would fall through to .tmp and .bak -- which hold the same
        # record -- and raise, leaving the device unable to boot over one
        # switch the user set months ago.
        self._seed(
            _schedule("keep", "shkia"),
            _schedule("stale", "tset_hakohavim_tsom"),
        )

        repository = JsonRepository(self.data_dir)

        self.assertEqual(
            ["keep"], [s["id"] for s in repository.get_all("schedules")]
        )

    def test_removes_stale_schedules_and_rewrites_the_file(self):
        path = self._seed(
            _schedule("keep", "tset_hakohavim"),
            _schedule("drop", "tset_hakohavim_tsom"),
            _schedule("drop-offset", "tset_hakohavim_tsom", "zman_offset"),
        )
        repository = JsonRepository(self.data_dir)

        summary = apply_all(repository)

        self.assertEqual(
            {"drop", "drop-offset"},
            {entry["id"] for entry in summary["removed_schedules"]},
        )
        with open(path) as handle:
            self.assertEqual(["keep"], [s["id"] for s in json.load(handle)])

    def test_reports_what_it_removed_rather_than_removing_silently(self):
        # The point of the migration: a switch the user configured stops
        # firing, and they are told which one and why.
        self._seed(_schedule("sch-9", "tset_hakohavim_tsom"))
        repository = JsonRepository(self.data_dir)

        entry = apply_all(repository)["removed_schedules"][0]

        self.assertEqual("sch-9", entry["id"])
        self.assertEqual("tset_hakohavim_tsom", entry["zman"])
        self.assertEqual("boiler", entry["name"])

    def test_second_start_is_quiet(self):
        # Until the file is rewritten every restart would re-drop and re-report
        # the same records forever.
        self._seed(
            _schedule("keep", "shkia"),
            _schedule("stale", "tset_hakohavim_tsom"),
        )
        apply_all(JsonRepository(self.data_dir))

        reopened = JsonRepository(self.data_dir)
        self.assertEqual({}, apply_all(reopened))
        self.assertEqual(["keep"], [s["id"] for s in reopened.get_all("schedules")])

    def test_a_stale_schedule_is_reported_once_after_backup_recovery(self):
        # An unreadable primary sends the loader to .bak, which holds the same
        # records. Without de-duplication the user is told the same switch was
        # removed two or three times.
        stale = _schedule("stale", "tset_hakohavim_tsom")
        path = self._seed(_schedule("keep", "shkia"), stale)
        with open(path + ".bak", "w") as handle:
            json.dump([_schedule("keep", "shkia"), stale], handle)
        with open(path, "w") as handle:
            handle.write("{ this is not json")

        repository = JsonRepository(self.data_dir)
        removed = apply_all(repository)["removed_schedules"]

        self.assertEqual(["stale"], [entry["id"] for entry in removed])
        self.assertEqual(["keep"],
                         [s["id"] for s in repository.get_all("schedules")])

    def test_healthy_data_is_untouched(self):
        self._seed(_schedule("keep", "shkia"))
        repository = JsonRepository(self.data_dir)

        self.assertEqual({}, apply_all(repository))
        self.assertEqual(1, len(repository.get_all("schedules")))

    def test_genuinely_corrupt_data_still_raises(self):
        # Dropping retired records must not have turned the loader into
        # something that tolerates a broken file.
        with open(os.path.join(self.data_dir, "schedules.json"), "w") as handle:
            handle.write("{not json")

        with self.assertRaises(Exception):
            JsonRepository(self.data_dir)

    def test_in_memory_repositories_are_handled_too(self):
        repository = MemoryRepository()
        repository.upsert("schedules", _schedule("keep", "shkia"))

        self.assertEqual({}, apply_all(repository))
        self.assertEqual(1, len(repository.get_all("schedules")))

    def test_every_surviving_zman_key_still_validates(self):
        # Guards the pair: a key removed from ZMAN_KEYS without being retired
        # would leave schedules that neither validate nor get cleaned up.
        for zman in sorted(ZMAN_KEYS):
            with self.subTest(zman=zman):
                self.assertTrue(validate_schedule(_schedule("sch", zman)))


class ElevationBackfillTests(unittest.TestCase):
    """A settings file written before elevation was a field must not inherit
    the default one, which is Jerusalem's."""

    def setUp(self):
        self.data_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.data_dir, True)
        self.repository = MemoryRepository()

    def _settings(self, stored):
        # Built with SETTINGS_DEFAULTS exactly as every composition root does.
        # Without them the store has no default elevation to shadow the missing
        # one, and these tests would pass while production stayed broken --
        # which is how the bug got this far.
        path = os.path.join(self.data_dir, "settings.json")
        with open(path, "w") as handle:
            json.dump(stored, handle)
        return SettingsStore(path, defaults=SETTINGS_DEFAULTS)

    def test_coastal_device_does_not_inherit_jerusalems_altitude(self):
        # The bug this exists for. Tel Aviv at 779 m would move sunset nearly
        # five minutes -- the same silent failure the elevation work removed.
        settings = self._settings(
            {"city": "תל אביב", "lat": 32.0853, "lon": 34.7818})

        summary = apply_all(self.repository, settings)

        self.assertEqual(20, summary["elevation"])
        self.assertEqual(20, settings.get()["elevation"])

    def test_resolves_a_mountain_city_from_its_coordinates(self):
        settings = self._settings(
            {"city": "צפת", "lat": 32.9646, "lon": 35.496})

        self.assertEqual(780, apply_all(self.repository, settings)["elevation"])

    def test_unknown_coordinates_fall_back_to_sea_level(self):
        # Sea level is what the system computed before elevation was wired in,
        # so an unrecognised location keeps the conservative answer rather than
        # borrowing an unrelated city's.
        settings = self._settings({"city": "somewhere", "lat": 12.0, "lon": 99.0})

        self.assertEqual(0, apply_all(self.repository, settings)["elevation"])

    def test_an_explicit_elevation_is_never_overwritten(self):
        settings = self._settings(
            {"city": "תל אביב", "lat": 32.0853, "lon": 34.7818, "elevation": 5})

        self.assertEqual({}, apply_all(self.repository, settings))
        self.assertEqual(5, settings.get()["elevation"])

    def test_a_stored_zero_counts_as_explicit(self):
        # 0 is a real elevation, not a missing one. Treating it as absent would
        # re-resolve it on every boot and quietly overwrite a deliberate choice.
        settings = self._settings(
            {"city": "צפת", "lat": 32.9646, "lon": 35.496, "elevation": 0})

        self.assertEqual({}, apply_all(self.repository, settings))
        self.assertEqual(0, settings.get()["elevation"])

    def test_second_boot_is_quiet(self):
        settings = self._settings({"city": "חיפה", "lat": 32.8191, "lon": 34.9983})

        self.assertEqual(14, apply_all(self.repository, settings)["elevation"])
        self.assertEqual({}, apply_all(self.repository, settings))

    def test_migration_is_reported(self):
        settings = self._settings({"lat": 32.0853, "lon": 34.7818})

        lines = describe(apply_all(self.repository, settings))

        self.assertEqual(1, len(lines))
        self.assertIn("20", lines[0])

    def test_a_device_still_on_the_default_location_keeps_its_elevation(self):
        # A fresh device has no settings file at all. Its effective location is
        # the default one, so it must get that location's elevation, not 0.
        path = os.path.join(self.data_dir, "settings.json")
        settings = SettingsStore(path, defaults=SETTINGS_DEFAULTS)

        self.assertEqual(
            SETTINGS_DEFAULTS["elevation"],
            apply_all(self.repository, settings)["elevation"],
        )

    def test_the_default_elevation_does_not_hide_a_missing_one(self):
        # The regression guard. SettingsStore.get() merges defaults, so a
        # backfill reading it would see the default 779 on a Tel Aviv device,
        # conclude the value was set, and leave sunset five minutes wrong.
        settings = self._settings({"lat": 32.0853, "lon": 34.7818})

        self.assertIsNone(settings.stored().get("elevation"))
        self.assertEqual(SETTINGS_DEFAULTS["elevation"],
                         settings.get()["elevation"])
        self.assertEqual(20, apply_all(self.repository, settings)["elevation"])

    def test_settings_are_optional(self):
        # Callers without a settings store still get the schedule migrations.
        self.assertEqual({}, apply_all(self.repository))


if __name__ == "__main__":
    unittest.main()
