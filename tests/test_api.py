"""Tests for the transport-agnostic Api dispatcher (application/api.py).

The HTTP routes are covered end-to-end in test_routes.py; these tests pin
the dispatch contract itself — the one the USB-serial channel will speak.
"""

import asyncio
import unittest

from smart_kosher.adapters import (
    H2Simulator, MemoryEventJournal, MemoryRepository,
)
from smart_kosher.application.api import (
    Api, ApiError, BAD_REQUEST, CONFLICT, NOT_FOUND, UNSUPPORTED,
)
from smart_kosher.application.control_service import ControlService
from smart_kosher.application.crud_service import CrudService
from smart_kosher.application.device_time import DeviceTimeService
from smart_kosher.application.executor import Executor
from smart_kosher.application.views import ViewService


def dispatch(api, op, params=None):
    """Sync facade over the async Api.dispatch for test brevity."""
    return asyncio.run(api.dispatch(op, params))


class FakeSettings:
    def __init__(self, values=None):
        self._values = dict(values or {})
        self.load_error = None

    def get(self):
        return dict(self._values)

    def update(self, values):
        self._values.update(values)


def _api(repo=None, clock=None):
    repo = repo if repo is not None else MemoryRepository()
    executor = Executor(H2Simulator(["sent_to_zigbee"]), MemoryEventJournal())
    return Api(
        CrudService(repo),
        ControlService(executor, repo),
        FakeSettings({"utc_offset_minutes": 120, "in_israel": True}),
        views=ViewService(repo),
        device_time=DeviceTimeService(clock),
    )


def _kind(callable_, *args):
    try:
        result = callable_(*args)
        if asyncio.iscoroutine(result):
            asyncio.run(result)
    except ApiError as exc:
        return exc.kind
    return None


class DispatchContractTests(unittest.TestCase):
    def test_unknown_op_is_bad_request(self):
        api = _api()
        self.assertEqual(BAD_REQUEST, _kind(api.dispatch, "no.such_op", {}))

    def test_params_must_be_dict(self):
        api = _api()
        self.assertEqual(BAD_REQUEST, _kind(api.dispatch, "zones.list", []))

    def test_none_params_allowed(self):
        self.assertEqual([], dispatch(_api(), "zones.list"))

    def test_crud_roundtrip(self):
        api = _api()
        zone = dispatch(api, "zones.create", {"data": {"name": "סלון"}})
        self.assertTrue(zone["id"].startswith("z_"))
        listed = dispatch(api, "zones.list")
        self.assertEqual([zone["id"]], [z["id"] for z in listed])
        updated = dispatch(api, 
            "zones.update", {"id": zone["id"], "data": {"name": "מטבח"}})
        self.assertEqual("מטבח", updated["name"])
        self.assertIsNone(dispatch(api, "zones.delete", {"id": zone["id"]}))
        self.assertEqual([], dispatch(api, "zones.list"))

    def test_missing_entity_is_not_found(self):
        api = _api()
        self.assertEqual(
            NOT_FOUND,
            _kind(api.dispatch, "zones.update",
                  {"id": "z_missing", "data": {"name": "x"}}))

    def test_delete_zone_in_use_is_conflict(self):
        api = _api()
        zone = dispatch(api, "zones.create", {"data": {"name": "סלון"}})
        dispatch(api, "endpoints.create",
                     {"data": {"name": "אור", "zone_id": zone["id"]}})
        self.assertEqual(
            CONFLICT, _kind(api.dispatch, "zones.delete", {"id": zone["id"]}))

    def test_time_set_without_rtc_is_unsupported(self):
        api = _api(clock=None)
        self.assertEqual(
            UNSUPPORTED,
            _kind(api.dispatch, "time.set",
                  {"year": 2026, "month": 7, "day": 8,
                   "hour": 12, "minute": 0, "second": 0}))

    def test_control_send_executes(self):
        api = _api()
        ep = dispatch(api, "endpoints.create", {"data": {"name": "אור"}})
        result = dispatch(api, "control.send", {
            "target_type": "endpoint", "target_id": ep["id"],
            "action_type": "on",
        })
        self.assertEqual("executed", result["status"])

    def test_ops_lists_every_command(self):
        ops = _api().ops()
        for expected in ("zones.create", "schedules.upcoming", "control.send",
                         "settings.update", "today.get", "time.set",
                         "status.get"):
            self.assertIn(expected, ops)


class FakeZigbee:
    def __init__(self):
        self.permit_calls = []

    def devices(self):
        return {"a4:c1:38:6b:47:9d:c2:55": {"short_addr": "0xa7d8",
                                            "endpoint": 1,
                                            "reporting": True,
                                            "on_off": True}}

    def permit_join(self, duration):
        self.permit_calls.append(duration)
        return {"status": "sent_to_zigbee", "command_id": "permit_join-1"}


class ZigbeeOpsTests(unittest.TestCase):
    def _api(self, zigbee):
        repo = MemoryRepository()
        executor = Executor(H2Simulator(["sent_to_zigbee"]),
                            MemoryEventJournal())
        return Api(
            CrudService(repo),
            ControlService(executor, repo),
            FakeSettings({"utc_offset_minutes": 120, "in_israel": True}),
            views=ViewService(repo),
            device_time=DeviceTimeService(None),
            zigbee=zigbee,
        )

    def test_zigbee_ops_absent_without_gateway(self):
        api = self._api(None)
        self.assertNotIn("zigbee.devices", api.ops())
        with self.assertRaises(ApiError) as ctx:
            dispatch(api, "zigbee.permit_join", {"duration": 60})
        self.assertEqual(BAD_REQUEST, ctx.exception.kind)

    def test_zigbee_devices_returns_registry_view(self):
        data = dispatch(self._api(FakeZigbee()), "zigbee.devices", {})
        self.assertIn("a4:c1:38:6b:47:9d:c2:55", data)
        self.assertTrue(data["a4:c1:38:6b:47:9d:c2:55"]["on_off"])

    def test_permit_join_defaults_and_validates_duration(self):
        zigbee = FakeZigbee()
        api = self._api(zigbee)
        dispatch(api, "zigbee.permit_join", {})
        self.assertEqual([180], zigbee.permit_calls)
        for bad in (0, 255, "60", True, -1):
            with self.assertRaises(ApiError):
                dispatch(api, "zigbee.permit_join", {"duration": bad})


class FakeClock:
    def __init__(self, now):
        self._now = now

    def now_utc(self):
        return self._now


class ViewClockInjectionTests(unittest.TestCase):
    def test_local_today_rolls_past_midnight(self):
        # 22:30 UTC + 120 minutes offset = 00:30 local, next day.
        views = ViewService(clock=FakeClock((2026, 7, 8, 22, 30)))
        settings = {"utc_offset_minutes": 120, "in_israel": False}
        self.assertEqual((2026, 7, 9), views.local_today(settings))

    def test_local_today_same_day(self):
        views = ViewService(clock=FakeClock((2026, 7, 8, 12, 0)))
        settings = {"utc_offset_minutes": 120, "in_israel": False}
        self.assertEqual((2026, 7, 8), views.local_today(settings))


if __name__ == "__main__":
    unittest.main()
