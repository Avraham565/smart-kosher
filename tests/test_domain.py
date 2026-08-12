import unittest

from smart_kosher.domain.actions import validate_action
from smart_kosher.domain.devices import (
    validate_endpoint,
    validate_group,
    validate_zone,
)
from smart_kosher.domain.events import Event, validate_event
from smart_kosher.domain.schedules import validate_schedule


class DomainTests(unittest.TestCase):
    def test_target_collections_agree_with_both_vocabularies(self):
        # The map is the join between two lists that live in different modules;
        # a target type added to one and forgotten in the other would make
        # manual control reject a target the domain accepts.
        from smart_kosher.domain.entities import (
            CONFIG_ENTITY_TYPES,
            TARGET_COLLECTIONS,
        )
        from smart_kosher.domain.schedules import TARGET_TYPES
        self.assertEqual(set(TARGET_TYPES), set(TARGET_COLLECTIONS))
        for collection in TARGET_COLLECTIONS.values():
            with self.subTest(collection=collection):
                self.assertIn(collection, CONFIG_ENTITY_TYPES)

    def test_actions_accept_only_supported_types(self):
        for action_type in ("on", "off", "toggle"):
            self.assertTrue(validate_action(action_type))
        for action_type in ("dim", "set_level", "unsupported"):
            with self.assertRaises(ValueError):
                validate_action(action_type, {})

    def test_device_schemas(self):
        self.assertTrue(validate_zone({"id": "kitchen", "name": "Kitchen"}))
        self.assertTrue(validate_endpoint({
            "id": "light-1",
            "name": "Main light",
            "zone_id": "kitchen",
            "device_type": "switch",
            "capabilities": ["on", "off"],
        }))
        self.assertTrue(validate_group({
            "id": "all-lights",
            "name": "All lights",
            "member_ids": ["light-1"],
        }))
        with self.assertRaises(ValueError):
            validate_group({"id": "g", "member_ids": ["x", "x"]})

    def test_a_fully_populated_schedule_validates(self):
        self.assertTrue(validate_schedule({
            "id": "schedule-1",
            "target_type": "group",
            "target_id": "all",
            "action_type": "on",
            "action_data": {},
            "trigger_type": "fixed_time",
            "trigger_data": {"h": 12, "m": 0},
            "recurrence_type": "daily",
            "recurrence_data": {},
        }))

    def test_validation_does_not_mutate_what_it_is_given(self):
        # Entities travel as plain dicts, so the validators are the only thing
        # standing between a caller's object and a surprise edit.
        zone = {"id": "kitchen", "name": "Kitchen"}
        endpoint = {"id": "light", "name": "Main light",
                    "capabilities": ["on", "off"]}
        group = {"id": "lights", "name": "All lights", "member_ids": ["light"]}
        for entity, validator in ((zone, validate_zone),
                                  (endpoint, validate_endpoint),
                                  (group, validate_group)):
            with self.subTest(entity=entity["id"]):
                before = repr(entity)
                self.assertTrue(validator(entity))
                self.assertEqual(before, repr(entity))

    def test_schedule_rejects_toggle_action(self):
        base = {
            "id": "sch-1", "target_type": "endpoint", "target_id": "ep1",
            "trigger_type": "fixed_time", "trigger_data": {"h": 18, "m": 0},
            "recurrence_type": "daily", "recurrence_data": {},
        }
        for action in ("on", "off"):
            self.assertTrue(validate_schedule({**base, "action_type": action}))
        with self.assertRaises(ValueError):
            validate_schedule({**base, "action_type": "toggle"})

    def test_event_rejects_invalid_source_date(self):
        with self.assertRaises(ValueError):
            validate_event({
                "event_id": "event-1",
                "schedule_id": "schedule-1",
                "source_date": (2026, 2, 30),
                "utc_minute": 100,
                "target_type": "group",
                "target_id": "all",
                "action_type": "on",
                "action_data": {},
            })

    def test_event_rejects_falsy_non_dict_action_data(self):
        for action_data in ([], 0, False, ""):
            with self.subTest(action_data=action_data):
                with self.assertRaises(ValueError):
                    Event(
                        event_id="event-1",
                        schedule_id="schedule-1",
                        source_date=(2026, 6, 8),
                        utc_minute=100,
                        target_type="group",
                        target_id="all",
                        action_type="on",
                        action_data=action_data,
                    )
        self.assertEqual(
            {},
            Event(
                event_id="event-1",
                schedule_id="schedule-1",
                source_date=(2026, 6, 8),
                utc_minute=100,
                target_type="group",
                target_id="all",
                action_type="on",
            ).to_dict()["action_data"],
        )


if __name__ == "__main__":
    unittest.main()
