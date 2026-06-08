import unittest

from smart_kosher.domain.actions import Action, validate_action
from smart_kosher.domain.devices import (
    Endpoint,
    Group,
    Zone,
    validate_endpoint,
    validate_group,
    validate_zone,
)
from smart_kosher.domain.events import Event, validate_event
from smart_kosher.domain.schedules import Schedule, validate_schedule


class DomainTests(unittest.TestCase):
    def test_actions_validate_dimming_range(self):
        self.assertEqual(50, Action("dim", {"level": 50}).to_dict()["action_data"]["level"])
        with self.assertRaises(ValueError):
            validate_action("dim", {"level": 101})
        with self.assertRaises(ValueError):
            validate_action("unsupported", {})

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

    def test_device_models_return_defensive_copies(self):
        for model in (
            Zone({"id": "kitchen", "name": "Kitchen"}),
            Endpoint({"id": "light", "capabilities": ["on", "off"]}),
            Group({"id": "lights", "member_ids": ["light"]}),
        ):
            copied = model.to_dict()
            copied["id"] = "changed"
            self.assertNotEqual("changed", model.id)

    def test_schedule_model_returns_defensive_copy(self):
        value = {
            "id": "schedule-1",
            "target_type": "group",
            "target_id": "all",
            "action_type": "on",
            "action_data": {},
            "trigger_type": "fixed_time",
            "trigger_data": {"h": 12, "m": 0},
            "recurrence_type": "daily",
            "recurrence_data": {},
        }
        model = Schedule(value)
        copied = model.to_dict()
        copied["trigger_data"]["h"] = 1
        self.assertEqual(12, model.to_dict()["trigger_data"]["h"])
        self.assertTrue(validate_schedule(value))

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
