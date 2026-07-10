"""Tests for the USB-serial channel protocol (serial_channel.handle_line)."""

import asyncio
import json
import unittest

from smart_kosher.adapters import (
    H2Simulator, MemoryEventJournal, MemoryRepository,
)
from smart_kosher.application.api import Api, ApiError, BAD_REQUEST
from smart_kosher.application.control_service import ControlService
from smart_kosher.application.crud_service import CrudService
from smart_kosher.application.device_time import DeviceTimeService
from smart_kosher.application.executor import Executor
from smart_kosher.application.views import ViewService
from smart_kosher.serial_channel import handle_line


class FakeSettings:
    def __init__(self, values=None):
        self._values = dict(values or {})
        self.load_error = None

    def get(self):
        return dict(self._values)

    def update(self, values):
        self._values.update(values)


def _api():
    repo = MemoryRepository()
    executor = Executor(H2Simulator(["sent_to_zigbee"]), MemoryEventJournal())
    return Api(
        CrudService(repo),
        ControlService(executor, repo),
        FakeSettings({"utc_offset_minutes": 120, "in_israel": True}),
        views=ViewService(repo),
        device_time=DeviceTimeService(None),
    )


def _roundtrip(api, request, extra_ops=None):
    return json.loads(
        asyncio.run(handle_line(api, json.dumps(request), extra_ops)))


class HandleLineTests(unittest.TestCase):
    def test_dispatch_roundtrip(self):
        api = _api()
        created = _roundtrip(api, {
            "op": "zones.create", "params": {"data": {"name": "סלון"}},
        })
        self.assertTrue(created["ok"])
        listed = _roundtrip(api, {"op": "zones.list"})
        self.assertEqual(created["data"]["id"], listed["data"][0]["id"])

    def test_id_echoed_on_success_and_error(self):
        api = _api()
        response = _roundtrip(api, {"op": "zones.list", "id": 42})
        self.assertEqual(42, response["id"])
        response = _roundtrip(api, {"op": "no.such_op", "id": "abc"})
        self.assertFalse(response["ok"])
        self.assertEqual("abc", response["id"])

    def test_invalid_json_line(self):
        response = json.loads(asyncio.run(handle_line(_api(), "{not json")))
        self.assertFalse(response["ok"])
        self.assertEqual("bad_request", response["kind"])

    def test_non_object_request(self):
        response = json.loads(asyncio.run(handle_line(_api(), "[1, 2]")))
        self.assertFalse(response["ok"])
        self.assertEqual("bad_request", response["kind"])

    def test_op_must_be_string(self):
        response = _roundtrip(_api(), {"op": 5})
        self.assertFalse(response["ok"])
        self.assertEqual("bad_request", response["kind"])

    def test_error_kind_passed_through(self):
        response = _roundtrip(_api(), {
            "op": "zones.update",
            "params": {"id": "z_missing", "data": {"name": "x"}},
        })
        self.assertFalse(response["ok"])
        self.assertEqual("not_found", response["kind"])

    def test_extra_op_called_and_wins_over_api(self):
        calls = []

        def provision(params):
            calls.append(params)
            return {"saved": True}

        response = _roundtrip(_api(), {
            "op": "wifi.provision",
            "params": {"ssid": "home", "password": "secret123"},
        }, extra_ops={"wifi.provision": provision})
        self.assertTrue(response["ok"])
        self.assertEqual({"saved": True}, response["data"])
        self.assertEqual([{"ssid": "home", "password": "secret123"}], calls)

    def test_extra_op_api_error_classified(self):
        def provision(params):
            raise ApiError(BAD_REQUEST, "ssid must be a non-empty string")

        response = _roundtrip(_api(), {"op": "wifi.provision"},
                              extra_ops={"wifi.provision": provision})
        self.assertFalse(response["ok"])
        self.assertEqual("bad_request", response["kind"])

    def test_extra_op_crash_reported_as_internal(self):
        def boom(params):
            raise RuntimeError("hardware exploded")

        response = _roundtrip(_api(), {"op": "wifi.provision"},
                              extra_ops={"wifi.provision": boom})
        self.assertFalse(response["ok"])
        self.assertEqual("internal", response["kind"])

    def test_ops_list_includes_api_and_extra(self):
        response = _roundtrip(_api(), {"op": "ops.list"},
                              extra_ops={"wifi.provision": lambda p: None})
        self.assertTrue(response["ok"])
        self.assertIn("zones.create", response["data"])
        self.assertIn("wifi.provision", response["data"])


if __name__ == "__main__":
    unittest.main()
