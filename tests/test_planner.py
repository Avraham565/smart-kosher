import unittest

from smart_kosher.application.planner import Planner, PlannerConfig
from smart_kosher.domain.schedules import validate_schedule
from smart_kosher.zmanim import (
    add_gregorian_days,
    compute_zmanim,
    israel_utc_offset_for_local,
)


class MemoryStorage:
    def __init__(self, schedules):
        self.schedules = schedules

    def get_all(self, entity_type):
        self.assert_entity_type(entity_type)
        return list(self.schedules)

    @staticmethod
    def assert_entity_type(entity_type):
        if entity_type != "schedules":
            raise AssertionError("unexpected entity type")


class VersionedMemoryStorage(MemoryStorage):
    def __init__(self, schedules):
        super().__init__(schedules)
        self.revision = 0
        self.get_all_calls = 0

    def get_all(self, entity_type):
        self.get_all_calls += 1
        return super().get_all(entity_type)

    def get_revision(self, entity_type):
        self.assert_entity_type(entity_type)
        return self.revision


def schedule(**overrides):
    value = {
        "id": "schedule-1",
        "enabled": True,
        "target_type": "group",
        "target_id": "all",
        "action_type": "on",
        "action_data": {},
        "trigger_type": "fixed_time",
        "trigger_data": {"h": 12, "m": 0},
        "recurrence_type": "daily",
        "recurrence_data": {},
    }
    value.update(overrides)
    return value


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.config = PlannerConfig(
            31.7683,
            35.2137,
            altitude=754,
            candle_offset=40,
            utc_offset_for_local=israel_utc_offset_for_local,
        )

    def test_fixed_local_time_uses_dst(self):
        planner = Planner(self.config, MemoryStorage([schedule()]))
        self.assertEqual(1, len(planner.due_events(2026, 6, 7, 9, 0)))
        self.assertEqual([], planner.due_events(2026, 6, 7, 10, 0))

    def test_fixed_time_near_midnight_matches_source_local_day(self):
        monday = schedule(
            trigger_data={"h": 0, "m": 30},
            recurrence_type="days_of_week",
            recurrence_data={"days": [0]},
        )
        planner = Planner(self.config, MemoryStorage([monday]))
        events = planner.due_events(2026, 6, 7, 21, 30)
        self.assertEqual(1, len(events))
        self.assertEqual((2026, 6, 8), events[0]["source_date"])

    def test_zman_offset_crossing_midnight_keeps_source_day(self):
        friday = schedule(
            trigger_type="zman_offset",
            trigger_data={"zman": "shkia", "offset": 600},
            recurrence_type="erev_assur_bemelacha",
        )
        planner = Planner(self.config, MemoryStorage([friday]))
        raw = compute_zmanim(2026, 6, 5, 31.7683, 35.2137, 754, 40)["shkia"] + 600
        utc_minute = int(raw // 1)
        event_date = add_gregorian_days(2026, 6, 5, utc_minute // 1440)
        minute_of_day = utc_minute % 1440
        events = planner.due_events(
            event_date[0], event_date[1], event_date[2],
            minute_of_day // 60, minute_of_day % 60,
        )
        self.assertEqual(1, len(events))
        self.assertEqual((2026, 6, 5), events[0]["source_date"])

    def test_catch_up_returns_missed_event(self):
        planner = Planner(self.config, MemoryStorage([schedule()]))
        events = planner.events_between(
            (2026, 6, 7, 8, 58),
            (2026, 6, 7, 9, 2),
        )
        self.assertEqual(1, len(events))

    def test_nonexistent_dst_start_time_is_skipped_and_reported(self):
        nonexistent = schedule(trigger_data={"h": 2, "m": 30})
        planner = Planner(self.config, MemoryStorage([nonexistent]))
        events = planner.events_between(
            (2026, 3, 26, 22, 0),
            (2026, 3, 28, 1, 0),
        )
        self.assertEqual(1, len(events))  # Saturday remains valid.
        self.assertEqual((2026, 3, 28), events[0]["source_date"])
        self.assertTrue(any("do not exist" in error["error"] for error in planner.last_errors))

    def test_invalid_schedule_is_reported_without_stopping_valid_ones(self):
        planner = Planner(
            self.config,
            MemoryStorage([schedule(id="valid"), {"id": "broken"}]),
        )
        events = planner.due_events(2026, 6, 7, 9, 0)
        self.assertEqual(1, len(events))
        self.assertEqual("valid", events[0]["schedule_id"])
        self.assertEqual(1, len(planner.last_errors))

    def test_schedule_validation(self):
        self.assertTrue(validate_schedule(schedule()))
        with self.assertRaises(ValueError):
            validate_schedule(schedule(trigger_data={"h": 24, "m": 0}))
        with self.assertRaises(ValueError):
            validate_schedule(schedule(recurrence_type="one_time", recurrence_data={"y": 2026, "m": 2, "d": 31}))
        with self.assertRaises(ValueError):
            validate_schedule(schedule(trigger_type="zman", trigger_data={"zman": "typo"}))
        with self.assertRaises(ValueError):
            validate_schedule(schedule(
                recurrence_type="gregorian_date",
                recurrence_data={"month": 2, "day": 30},
            ))
        with self.assertRaises(ValueError):
            validate_schedule(schedule(
                recurrence_type="days_of_week",
                recurrence_data={"days": []},
            ))

    def test_validation_rejects_falsy_non_dicts_and_boolean_numbers(self):
        for field in ("action_data", "trigger_data", "recurrence_data"):
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    validate_schedule(schedule(**{field: []}))
        with self.assertRaises(ValueError):
            validate_schedule(schedule(trigger_data={"h": True, "m": 0}))
        with self.assertRaises(ValueError):
            validate_schedule(schedule(
                trigger_type="zman_offset",
                trigger_data={"zman": "shkia", "offset": False},
            ))
        with self.assertRaises(ValueError):
            PlannerConfig(31.7683, 35.2137, utc_offset_minutes=True)

    def test_february_29_annual_schedule_runs_only_in_leap_years(self):
        leap_day = schedule(
            recurrence_type="gregorian_date",
            recurrence_data={"month": 2, "day": 29},
        )
        planner = Planner(self.config, MemoryStorage([leap_day]))
        self.assertTrue(validate_schedule(leap_day))
        self.assertEqual(1, len(planner.due_events(2024, 2, 29, 10, 0)))
        self.assertEqual([], planner.due_events(2025, 2, 28, 10, 0))

    def test_scheduler_reloads_versioned_storage_only_after_change(self):
        store = VersionedMemoryStorage([schedule()])
        planner = Planner(self.config, store)
        planner.due_events(2026, 6, 7, 9, 0)
        planner.due_events(2026, 6, 7, 10, 0)
        self.assertEqual(1, store.get_all_calls)

        store.schedules = []
        store.revision += 1
        self.assertEqual([], planner.due_events(2026, 6, 8, 9, 0))
        self.assertEqual(2, store.get_all_calls)

    def test_cached_schedule_action_data_is_not_exposed_by_events(self):
        store = VersionedMemoryStorage([
            schedule(action_data={"nested": {"value": 1}}),
        ])
        planner = Planner(self.config, store)
        event = planner.due_events(2026, 6, 7, 9, 0)[0]
        event["action_data"]["nested"]["value"] = 2
        next_event = planner.due_events(2026, 6, 8, 9, 0)[0]
        self.assertEqual(1, next_event["action_data"]["nested"]["value"])


if __name__ == "__main__":
    unittest.main()
