"""HTTP-level tests for all API routes via Microdot TestClient."""

import asyncio
import os
import tempfile
import unittest

from microdot.test_client import TestClient

from smart_kosher.adapters import (
    H2Simulator,
    MemoryEventJournal,
    MemoryRepository,
    SettingsStore,
)
from smart_kosher.application.control_service import ControlService
from smart_kosher.application.crud_service import CrudService
from smart_kosher.application.executor import Executor
from smart_kosher.web.server import create_app

# ── Helpers ───────────────────────────────────────────────────────────────────

def _minutes(hhmm):
    """"HH:MM" from the today view -> minutes since local midnight."""
    hours, minutes = hhmm.split(":")
    return int(hours) * 60 + int(minutes)


def _temp_settings_path():
    fd, path = tempfile.mkstemp(suffix=".json", prefix="sk_test_")
    os.close(fd)
    os.unlink(path)  # let SettingsStore create it fresh
    return path


def _build_client(gateway_responses=None):
    repo     = MemoryRepository()
    gateway  = H2Simulator(gateway_responses or ["sent_to_zigbee"])
    journal  = MemoryEventJournal()
    executor = Executor(gateway, journal)
    crud     = CrudService(repo)
    control  = ControlService(executor, repo)
    settings = SettingsStore(
        _temp_settings_path(),
        # candle_offset/tzais_offset are seeded here ON PURPOSE, standing in for
        # a device whose settings.json was written before the two became fixed
        # product rules -- a stored value beats a default, so this is exactly
        # the case that must NOT be able to move Shabbat.
        #
        # Both MUST differ from what the code computes, or the assertions prove
        # nothing. This seeded 18 while CANDLE_OFFSET_MINUTES was 20; when the
        # constant later became 18 the two collided and the test passed whether
        # the API reported the constant or echoed storage. 40 is the old
        # Jerusalem custom and is not a value any constant here holds.
        # See test_fixed_shabbat_offsets_*.
        defaults={"city": "ירושלים", "lat": 31.7683, "lon": 35.2137,
                  "utc_offset_minutes": 120, "candle_offset": 40, "tzais_offset": 40},
    )
    app = create_app(crud, control, settings, repo)
    return TestClient(app), crud


class AsyncCase(unittest.TestCase):
    """Mixin that runs async coroutines synchronously."""
    def _run(self, coro):
        return asyncio.run(coro)


_ZONE_BODY    = {"name": "סלון"}
_EP_BODY      = {"name": "אור ראשי"}
_GROUP_BODY   = {"name": "כל הסלון", "member_ids": []}
_SCHEDULE_BODY = {
    "name": "תזמון ערב",
    "enabled": True,
    "target_type": "endpoint",
    "target_id": "ep_placeholder",
    "trigger_type": "fixed_time",
    "trigger_data": {"h": 20, "m": 0},
    "recurrence_type": "daily",
    "recurrence_data": {},
    "action_type": "on",
    "action_data": {},
}


# ── /api/zones ────────────────────────────────────────────────────────────────

class TestZonesRoutes(AsyncCase):

    async def _setup(self):
        client, crud = _build_client()
        return client

    def test_list_empty(self):
        async def go():
            client = await self._setup()
            res = await client.get("/api/zones")
            self.assertEqual(200, res.status_code)
            self.assertTrue(res.json["ok"])
            self.assertEqual([], res.json["data"])
        self._run(go())

    def test_create_returns_201_with_id(self):
        async def go():
            client = await self._setup()
            res = await client.post("/api/zones", body=_ZONE_BODY)
            self.assertEqual(201, res.status_code)
            self.assertTrue(res.json["ok"])
            zone = res.json["data"]
            self.assertTrue(zone["id"].startswith("z_"))
            self.assertEqual("סלון", zone["name"])
        self._run(go())

    def test_create_then_list(self):
        async def go():
            client = await self._setup()
            await client.post("/api/zones", body=_ZONE_BODY)
            await client.post("/api/zones", body={"name": "מטבח"})
            res = await client.get("/api/zones")
            self.assertEqual(2, len(res.json["data"]))
        self._run(go())

    def test_update(self):
        async def go():
            client = await self._setup()
            created = (await client.post("/api/zones", body=_ZONE_BODY)).json["data"]
            res = await client.put(f"/api/zones/{created['id']}", body={"name": "מטבח"})
            self.assertEqual(200, res.status_code)
            self.assertEqual("מטבח", res.json["data"]["name"])
            self.assertEqual(created["id"], res.json["data"]["id"])
        self._run(go())

    def test_delete(self):
        async def go():
            client = await self._setup()
            created = (await client.post("/api/zones", body=_ZONE_BODY)).json["data"]
            res = await client.delete(f"/api/zones/{created['id']}")
            self.assertEqual(200, res.status_code)
            after = (await client.get("/api/zones")).json["data"]
            self.assertEqual([], after)
        self._run(go())

    def test_update_not_found_returns_404(self):
        async def go():
            client = await self._setup()
            res = await client.put("/api/zones/z_nonexistent", body={"name": "x"})
            self.assertEqual(404, res.status_code)
            self.assertFalse(res.json["ok"])
        self._run(go())

    def test_delete_not_found_returns_404(self):
        async def go():
            client = await self._setup()
            res = await client.delete("/api/zones/z_nonexistent")
            self.assertEqual(404, res.status_code)
        self._run(go())

    def test_create_bad_json_body_returns_400(self):
        async def go():
            client = await self._setup()
            res = await client.post("/api/zones", body="not json",
                                    headers={"Content-Type": "text/plain"})
            self.assertEqual(400, res.status_code)
            self.assertFalse(res.json["ok"])
        self._run(go())


# ── /api/endpoints ────────────────────────────────────────────────────────────

class TestEndpointsRoutes(AsyncCase):

    def test_list_empty(self):
        async def go():
            client, _ = _build_client()
            res = await client.get("/api/endpoints")
            self.assertEqual(200, res.status_code)
            self.assertEqual([], res.json["data"])
        self._run(go())

    def test_create_minimal(self):
        async def go():
            client, _ = _build_client()
            res = await client.post("/api/endpoints", body=_EP_BODY)
            self.assertEqual(201, res.status_code)
            ep = res.json["data"]
            self.assertTrue(ep["id"].startswith("ep_"))
            self.assertEqual("אור ראשי", ep["name"])
        self._run(go())

    def test_create_with_optional_fields(self):
        async def go():
            client, _ = _build_client()
            body = {"name": "חיישן", "ieee_address": "0x0011223344556677", "zigbee_endpoint": 1}
            res = await client.post("/api/endpoints", body=body)
            self.assertEqual(201, res.status_code)
        self._run(go())

    def test_create_invalid_zigbee_endpoint_returns_400(self):
        async def go():
            client, _ = _build_client()
            res = await client.post("/api/endpoints",
                                    body={"name": "x", "zigbee_endpoint": 999})
            self.assertEqual(400, res.status_code)
            self.assertFalse(res.json["ok"])
        self._run(go())

    def test_update_endpoint(self):
        async def go():
            client, _ = _build_client()
            ep = (await client.post("/api/endpoints", body=_EP_BODY)).json["data"]
            res = await client.put(f"/api/endpoints/{ep['id']}", body={"name": "ספוט"})
            self.assertEqual(200, res.status_code)
            self.assertEqual("ספוט", res.json["data"]["name"])
        self._run(go())

    def test_delete_endpoint(self):
        async def go():
            client, _ = _build_client()
            ep = (await client.post("/api/endpoints", body=_EP_BODY)).json["data"]
            res = await client.delete(f"/api/endpoints/{ep['id']}")
            self.assertEqual(200, res.status_code)
            self.assertEqual([], (await client.get("/api/endpoints")).json["data"])
        self._run(go())

    def test_update_not_found(self):
        async def go():
            client, _ = _build_client()
            res = await client.put("/api/endpoints/ep_ghost", body={"name": "x"})
            self.assertEqual(404, res.status_code)
        self._run(go())

    def test_delete_not_found(self):
        async def go():
            client, _ = _build_client()
            res = await client.delete("/api/endpoints/ep_ghost")
            self.assertEqual(404, res.status_code)
        self._run(go())


# ── /api/groups ───────────────────────────────────────────────────────────────

class TestGroupsRoutes(AsyncCase):

    def test_list_empty(self):
        async def go():
            client, _ = _build_client()
            res = await client.get("/api/groups")
            self.assertEqual(200, res.status_code)
            self.assertEqual([], res.json["data"])
        self._run(go())

    def test_create_group(self):
        async def go():
            client, _ = _build_client()
            res = await client.post("/api/groups", body=_GROUP_BODY)
            self.assertEqual(201, res.status_code)
            grp = res.json["data"]
            self.assertTrue(grp["id"].startswith("grp_"))
        self._run(go())

    def test_create_group_with_members(self):
        async def go():
            client, crud = _build_client()
            ep = crud.create("endpoints", {"name": "מנורה"})
            body = {"name": "כולם", "member_ids": [ep["id"]]}
            res = await client.post("/api/groups", body=body)
            self.assertEqual(201, res.status_code)
            self.assertIn(ep["id"], res.json["data"]["member_ids"])
        self._run(go())

    def test_update_group(self):
        async def go():
            client, _ = _build_client()
            grp = (await client.post("/api/groups", body=_GROUP_BODY)).json["data"]
            res = await client.put(f"/api/groups/{grp['id']}", body={"name": "עדכון"})
            self.assertEqual(200, res.status_code)
            self.assertEqual("עדכון", res.json["data"]["name"])
        self._run(go())

    def test_delete_group(self):
        async def go():
            client, _ = _build_client()
            grp = (await client.post("/api/groups", body=_GROUP_BODY)).json["data"]
            res = await client.delete(f"/api/groups/{grp['id']}")
            self.assertEqual(200, res.status_code)
            self.assertEqual([], (await client.get("/api/groups")).json["data"])
        self._run(go())

    def test_update_not_found(self):
        async def go():
            client, _ = _build_client()
            res = await client.put("/api/groups/grp_ghost", body={"name": "x"})
            self.assertEqual(404, res.status_code)
        self._run(go())

    def test_delete_not_found(self):
        async def go():
            client, _ = _build_client()
            res = await client.delete("/api/groups/grp_ghost")
            self.assertEqual(404, res.status_code)
        self._run(go())


# ── /api/schedules ────────────────────────────────────────────────────────────

class TestSchedulesRoutes(AsyncCase):

    def test_list_empty(self):
        async def go():
            client, _ = _build_client()
            res = await client.get("/api/schedules")
            self.assertEqual(200, res.status_code)
            self.assertEqual([], res.json["data"])
        self._run(go())

    def test_create_valid_schedule(self):
        async def go():
            client, _ = _build_client()
            res = await client.post("/api/schedules", body=_SCHEDULE_BODY)
            self.assertEqual(201, res.status_code)
            self.assertTrue(res.json["data"]["id"].startswith("sch_"))
        self._run(go())

    def test_create_invalid_action_returns_400(self):
        async def go():
            client, _ = _build_client()
            bad = dict(_SCHEDULE_BODY, action_type="dim")
            res = await client.post("/api/schedules", body=bad)
            self.assertEqual(400, res.status_code)
            self.assertFalse(res.json["ok"])
        self._run(go())

    def test_update_schedule(self):
        async def go():
            client, _ = _build_client()
            sch = (await client.post("/api/schedules", body=_SCHEDULE_BODY)).json["data"]
            updated = dict(_SCHEDULE_BODY, name="שם חדש")
            res = await client.put(f"/api/schedules/{sch['id']}", body=updated)
            self.assertEqual(200, res.status_code)
            self.assertEqual("שם חדש", res.json["data"]["name"])
        self._run(go())

    def test_delete_schedule(self):
        async def go():
            client, _ = _build_client()
            sch = (await client.post("/api/schedules", body=_SCHEDULE_BODY)).json["data"]
            res = await client.delete(f"/api/schedules/{sch['id']}")
            self.assertEqual(200, res.status_code)
            self.assertEqual([], (await client.get("/api/schedules")).json["data"])
        self._run(go())

    def test_patch_enabled_true(self):
        async def go():
            client, _ = _build_client()
            sch = (await client.post("/api/schedules", body=dict(_SCHEDULE_BODY, enabled=False))).json["data"]
            res = await client.patch(f"/api/schedules/{sch['id']}/enabled",
                                     body={"enabled": True})
            self.assertEqual(200, res.status_code)
            self.assertTrue(res.json["data"]["enabled"])
        self._run(go())

    def test_patch_enabled_false(self):
        async def go():
            client, _ = _build_client()
            sch = (await client.post("/api/schedules", body=_SCHEDULE_BODY)).json["data"]
            res = await client.patch(f"/api/schedules/{sch['id']}/enabled",
                                     body={"enabled": False})
            self.assertEqual(200, res.status_code)
            self.assertFalse(res.json["data"]["enabled"])
        self._run(go())

    def test_patch_enabled_not_bool_returns_400(self):
        async def go():
            client, _ = _build_client()
            sch = (await client.post("/api/schedules", body=_SCHEDULE_BODY)).json["data"]
            res = await client.patch(f"/api/schedules/{sch['id']}/enabled",
                                     body={"enabled": "yes"})
            self.assertEqual(400, res.status_code)
            self.assertFalse(res.json["ok"])
        self._run(go())

    def test_patch_enabled_not_found_returns_404(self):
        async def go():
            client, _ = _build_client()
            res = await client.patch("/api/schedules/sch_ghost/enabled",
                                     body={"enabled": True})
            self.assertEqual(404, res.status_code)
        self._run(go())

    def test_update_not_found(self):
        async def go():
            client, _ = _build_client()
            res = await client.put("/api/schedules/sch_ghost", body=_SCHEDULE_BODY)
            self.assertEqual(404, res.status_code)
        self._run(go())

    def test_delete_not_found(self):
        async def go():
            client, _ = _build_client()
            res = await client.delete("/api/schedules/sch_ghost")
            self.assertEqual(404, res.status_code)
        self._run(go())


# ── /api/control ──────────────────────────────────────────────────────────────

class TestControlRoute(AsyncCase):

    def _client_with_endpoint(self, gateway_responses=None):
        client, crud = _build_client(gateway_responses)
        ep = crud.create("endpoints", {"name": "מנורה"})
        grp = crud.create("groups", {"name": "סלון", "member_ids": [ep["id"]]})
        return client, ep["id"], grp["id"]

    def test_send_on_to_endpoint(self):
        async def go():
            client, ep_id, _ = self._client_with_endpoint(["sent_to_zigbee"])
            res = await client.post("/api/control", body={
                "target_type": "endpoint", "target_id": ep_id, "action_type": "on"
            })
            self.assertEqual(200, res.status_code)
            self.assertEqual("executed", res.json["data"]["status"])
        self._run(go())

    def test_send_off_to_endpoint(self):
        async def go():
            client, ep_id, _ = self._client_with_endpoint(["sent_to_zigbee"])
            res = await client.post("/api/control", body={
                "target_type": "endpoint", "target_id": ep_id, "action_type": "off"
            })
            self.assertEqual(200, res.status_code)
            self.assertEqual("executed", res.json["data"]["status"])
        self._run(go())

    def test_send_toggle_to_endpoint(self):
        async def go():
            client, ep_id, _ = self._client_with_endpoint(["sent_to_zigbee"])
            res = await client.post("/api/control", body={
                "target_type": "endpoint", "target_id": ep_id, "action_type": "toggle"
            })
            self.assertEqual(200, res.status_code)
        self._run(go())

    def test_send_to_group(self):
        async def go():
            client, _, grp_id = self._client_with_endpoint(["sent_to_zigbee"])
            res = await client.post("/api/control", body={
                "target_type": "group", "target_id": grp_id, "action_type": "off"
            })
            self.assertEqual(200, res.status_code)
            self.assertEqual("executed", res.json["data"]["status"])
        self._run(go())

    def test_unknown_target_id_returns_404(self):
        async def go():
            client, _, _ = self._client_with_endpoint()
            res = await client.post("/api/control", body={
                "target_type": "endpoint", "target_id": "ep_ghost", "action_type": "on"
            })
            self.assertEqual(404, res.status_code)
        self._run(go())

    def test_invalid_action_returns_400(self):
        async def go():
            client, ep_id, _ = self._client_with_endpoint()
            res = await client.post("/api/control", body={
                "target_type": "endpoint", "target_id": ep_id, "action_type": "dim"
            })
            self.assertEqual(400, res.status_code)
            self.assertFalse(res.json["ok"])
        self._run(go())

    def test_invalid_target_type_returns_400(self):
        async def go():
            client, ep_id, _ = self._client_with_endpoint()
            res = await client.post("/api/control", body={
                "target_type": "device", "target_id": ep_id, "action_type": "on"
            })
            self.assertEqual(400, res.status_code)
        self._run(go())

    def test_retry_on_timeout(self):
        async def go():
            client, ep_id, _ = self._client_with_endpoint(["timeout", "sent_to_zigbee"])
            res = await client.post("/api/control", body={
                "target_type": "endpoint", "target_id": ep_id, "action_type": "on"
            })
            self.assertEqual(200, res.status_code)
            self.assertEqual(2, res.json["data"]["attempts"])
        self._run(go())

    def test_bad_json_returns_400(self):
        async def go():
            client, _, _ = self._client_with_endpoint()
            res = await client.post("/api/control", body="bad",
                                    headers={"Content-Type": "text/plain"})
            self.assertEqual(400, res.status_code)
        self._run(go())


# ── /api/settings ─────────────────────────────────────────────────────────────

class TestSettingsRoutes(AsyncCase):

    def test_get_settings_returns_defaults(self):
        async def go():
            client, _ = _build_client()
            res = await client.get("/api/settings")
            self.assertEqual(200, res.status_code)
            data = res.json["data"]
            self.assertEqual("ירושלים", data["city"])
            self.assertIn("device_time", data)
        self._run(go())

    def test_get_device_time_format(self):
        async def go():
            client, _ = _build_client()
            res = await client.get("/api/settings")
            dt = res.json["data"]["device_time"]
            # format: YYYY-MM-DD HH:MM:SS
            self.assertRegex(dt, r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
        self._run(go())

    def test_update_city(self):
        async def go():
            client, _ = _build_client()
            res = await client.put("/api/settings", body={"city": "תל אביב"})
            self.assertEqual(200, res.status_code)
            self.assertEqual("תל אביב", res.json["data"]["city"])
        self._run(go())

    def test_update_multiple_keys(self):
        async def go():
            client, _ = _build_client()
            res = await client.put("/api/settings", body={
                "lat": 32.0853, "lon": 34.7818, "utc_offset_minutes": 180
            })
            self.assertEqual(200, res.status_code)
            data = res.json["data"]
            self.assertAlmostEqual(32.0853, data["lat"])
            self.assertEqual(180, data["utc_offset_minutes"])
        self._run(go())

    def test_update_unknown_key_returns_400(self):
        async def go():
            client, _ = _build_client()
            res = await client.put("/api/settings", body={"bogus_key": 99})
            self.assertEqual(400, res.status_code)
            self.assertFalse(res.json["ok"])
            self.assertIn("bogus_key", res.json["error"])
        self._run(go())

    def test_update_persists_across_get(self):
        async def go():
            client, _ = _build_client()
            await client.put("/api/settings", body={"city": "בני ברק"})
            res = await client.get("/api/settings")
            self.assertEqual("בני ברק", res.json["data"]["city"])
        self._run(go())

    def test_bad_json_returns_400(self):
        async def go():
            client, _ = _build_client()
            res = await client.put("/api/settings", body="not json",
                                   headers={"Content-Type": "text/plain"})
            self.assertEqual(400, res.status_code)
        self._run(go())

    def test_lat_string_returns_400(self):
        async def go():
            client, _ = _build_client()
            res = await client.put("/api/settings", body={"lat": "hello"})
            self.assertEqual(400, res.status_code)
            self.assertFalse(res.json["ok"])
            self.assertIn("lat", res.json["error"])
        self._run(go())

    def test_lon_bool_returns_400(self):
        async def go():
            client, _ = _build_client()
            res = await client.put("/api/settings", body={"lon": True})
            self.assertEqual(400, res.status_code)
        self._run(go())

    def test_utc_offset_float_returns_400(self):
        async def go():
            client, _ = _build_client()
            res = await client.put("/api/settings", body={"utc_offset_minutes": 1.5})
            self.assertEqual(400, res.status_code)
        self._run(go())

    def test_in_israel_string_returns_400(self):
        async def go():
            client, _ = _build_client()
            res = await client.put("/api/settings", body={"in_israel": "yes"})
            self.assertEqual(400, res.status_code)
        self._run(go())

    def test_city_empty_returns_400(self):
        async def go():
            client, _ = _build_client()
            res = await client.put("/api/settings", body={"city": ""})
            self.assertEqual(400, res.status_code)
        self._run(go())

    def test_valid_numeric_types_accepted(self):
        async def go():
            client, _ = _build_client()
            res = await client.put("/api/settings", body={
                "lat": 32.08, "lon": 34.78, "utc_offset_minutes": 120,
                "in_israel": True,
            })
            self.assertEqual(200, res.status_code)
        self._run(go())

    def test_lat_out_of_range_returns_400(self):
        async def go():
            client, _ = _build_client()
            res = await client.put("/api/settings", body={"lat": 91})
            self.assertEqual(400, res.status_code)
            self.assertIn("lat", res.json["error"])
        self._run(go())

    def test_lon_out_of_range_returns_400(self):
        async def go():
            client, _ = _build_client()
            res = await client.put("/api/settings", body={"lon": -200.5})
            self.assertEqual(400, res.status_code)
        self._run(go())

    def test_utc_offset_out_of_range_returns_400(self):
        async def go():
            client, _ = _build_client()
            res = await client.put("/api/settings", body={"utc_offset_minutes": 900})
            self.assertEqual(400, res.status_code)
        self._run(go())

    def test_fixed_shabbat_offsets_cannot_be_written(self):
        # candle_offset is a product rule, not a setting: 18 min before sunset,
        # everywhere in Israel. A write is rejected outright rather than
        # accepted into a file nothing reads. tzais_offset is rejected for a
        # different reason -- Shabbat exit is an angle now, so there is no such
        # quantity anywhere in the system to write to.
        async def go():
            client, _ = _build_client()
            for key in ("candle_offset", "tzais_offset"):
                res = await client.put("/api/settings", body={key: 25})
                self.assertEqual(400, res.status_code, key)
                self.assertIn(key, res.json["error"])
        self._run(go())

    def test_fixed_shabbat_offsets_survive_a_stale_settings_file(self):
        # The fixture seeds the pre-decision values, standing in for a device
        # provisioned before the rule existed. A stored value normally beats a
        # default, so without the keys being removed from the settings layer
        # entirely, that file would keep moving Shabbat forever -- and silently,
        # since nothing would report a disagreement.
        async def go():
            client, _ = _build_client()
            res = await client.get("/api/settings")
            self.assertEqual(200, res.status_code)
            self.assertEqual(18, res.json["data"]["candle_offset"])
            self.assertNotIn("tzais_offset", res.json["data"])
        self._run(go())

    def test_choosing_a_city_applies_its_whole_geography(self):
        # A city name is a location, not a label. If only the name changed, the
        # previous city's coordinates and elevation would keep deciding every
        # zman -- Tel Aviv computed at Jerusalem's 779 m is five minutes wrong.
        async def go():
            client, _ = _build_client()
            res = await client.put("/api/settings", body={"city": "tel_aviv"})
            self.assertEqual(200, res.status_code)
            data = res.json["data"]
            self.assertEqual("תל אביב", data["city"])
            self.assertAlmostEqual(32.0853, data["lat"], places=4)
            self.assertAlmostEqual(34.7818, data["lon"], places=4)
            self.assertEqual(20, data["elevation"])
        self._run(go())

    def test_choosing_a_city_by_its_hebrew_name_works_too(self):
        async def go():
            client, _ = _build_client()
            res = await client.put("/api/settings", body={"city": "צפת"})
            self.assertEqual(200, res.status_code)
            self.assertEqual(780, res.json["data"]["elevation"])
        self._run(go())

    def test_explicit_coordinates_beat_the_city_list(self):
        # Somewhere the list does not cover, described by hand.
        async def go():
            client, _ = _build_client()
            res = await client.put("/api/settings", body={
                "city": "tel_aviv", "lat": 31.5, "lon": 35.0, "elevation": 400})
            self.assertEqual(200, res.status_code)
            data = res.json["data"]
            self.assertAlmostEqual(31.5, data["lat"], places=4)
            self.assertEqual(400, data["elevation"])
        self._run(go())

    def test_an_unlisted_city_name_is_kept_as_written(self):
        async def go():
            client, _ = _build_client()
            res = await client.put("/api/settings", body={
                "city": "קוממיות", "lat": 31.6, "lon": 34.75, "elevation": 90})
            self.assertEqual(200, res.status_code)
            self.assertEqual("קוממיות", res.json["data"]["city"])
            self.assertEqual(90, res.json["data"]["elevation"])
        self._run(go())

    def test_the_city_list_is_offered_for_picking(self):
        async def go():
            client, _ = _build_client()
            res = await client.get("/api/settings/cities")
            self.assertEqual(200, res.status_code)
            cities = res.json["data"]
            self.assertEqual(40, len(cities))
            for city in cities:
                self.assertEqual(
                    {"id", "name_he", "lat", "lon", "elevation"}, set(city))
            # Sorted by name so the picker reads in order.
            self.assertEqual(sorted(c["name_he"] for c in cities),
                             [c["name_he"] for c in cities])
        self._run(go())

    def test_a_stale_settings_file_does_not_move_computed_zmanim(self):
        # The claim that matters: not just what /api/settings reports, but what
        # the zmanim themselves are computed from.
        async def go():
            client, _ = _build_client()
            res = await client.get("/api/today?date=2026-06-05")
            self.assertEqual(200, res.status_code)
            zmanim = res.json["data"]["zmanim"]
            shkia = _minutes(zmanim["shkia"])
            # Shabbat exit is 8.5 degrees below the horizon, not a stored
            # number of minutes -- in June that lands past 36 after sunset,
            # which is exactly what the old fixed offset got wrong.
            self.assertGreater(
                _minutes(zmanim["tset_hakohavim_shabbat"]) - shkia, 36)
            # candle lighting is measured from sea-level sunset, so at
            # Jerusalem's elevation the gap to the displayed shkia is larger
            # than 18 -- but it must still be a fixed 18 from its own anchor,
            # i.e. unaffected by anything stale in the settings file.
            self.assertLess(_minutes(zmanim["candle_lighting"]), shkia)
        self._run(go())


# ── /api/settings/cities ──────────────────────────────────────────────────────

class TestCitiesRoute(AsyncCase):

    def test_lists_packaged_cities(self):
        async def go():
            client, _ = _build_client()
            res = await client.get("/api/settings/cities")
            self.assertEqual(200, res.status_code)
            cities = res.json["data"]
            self.assertTrue(cities)
            for city in cities:
                self.assertIn("id", city)
                self.assertIn("name_he", city)
                self.assertIn("lat", city)
                self.assertIn("lon", city)
        self._run(go())


# ── /api/status ───────────────────────────────────────────────────────────────

class TestStatusRoute(AsyncCase):

    def test_status_shape(self):
        async def go():
            client, _ = _build_client()
            res = await client.get("/api/status")
            self.assertEqual(200, res.status_code)
            data = res.json["data"]
            self.assertIn("app_version", data)
            self.assertRegex(data["device_time"], r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
            self.assertIsNone(data["settings_load_error"])
            self.assertGreaterEqual(data["uptime_seconds"], 0)
            self.assertFalse(data["clock_unset"])
        self._run(go())


# ── /api/today ────────────────────────────────────────────────────────────────

class TestTodayRoute(AsyncCase):

    def test_explicit_date(self):
        async def go():
            client, _ = _build_client()
            res = await client.get("/api/today?date=2026-07-03")
            self.assertEqual(200, res.status_code)
            data = res.json["data"]
            self.assertEqual("2026-07-03", data["date"])
            # 18 Tammuz 5786, a Friday
            self.assertEqual({"year": 5786, "month": 4, "day": 18}, data["hebrew_date"])
            self.assertEqual(6, data["day_of_week"])
            self.assertFalse(data["is_shabbat"])
            self.assertRegex(data["zmanim"]["shkia"], r"^\d{2}:\d{2}$")
            self.assertRegex(data["zmanim"]["candle_lighting"], r"^\d{2}:\d{2}$")
        self._run(go())

    def test_shabbat_flag(self):
        async def go():
            client, _ = _build_client()
            res = await client.get("/api/today?date=2026-07-04")
            self.assertTrue(res.json["data"]["is_shabbat"])
        self._run(go())

    def test_dst_offset_reflected(self):
        async def go():
            client, _ = _build_client()
            july = (await client.get("/api/today?date=2026-07-03")).json["data"]
            january = (await client.get("/api/today?date=2026-01-02")).json["data"]
            self.assertEqual(180, july["utc_offset_minutes"])
            self.assertEqual(120, january["utc_offset_minutes"])
        self._run(go())

    def test_no_date_returns_today(self):
        async def go():
            client, _ = _build_client()
            res = await client.get("/api/today")
            self.assertEqual(200, res.status_code)
            self.assertRegex(res.json["data"]["date"], r"^\d{4}-\d{2}-\d{2}$")
        self._run(go())

    def test_bad_date_returns_400(self):
        async def go():
            client, _ = _build_client()
            res = await client.get("/api/today?date=not-a-date")
            self.assertEqual(400, res.status_code)
        self._run(go())

    def test_unset_clock_year_falls_back_to_fixed_offset(self):
        # A fresh device RTC reads 2000; Israeli DST rules start at 2013.
        # The view must not error — it falls back to the stored fixed offset.
        async def go():
            client, _ = _build_client()
            res = await client.get("/api/today?date=2000-01-01")
            self.assertEqual(200, res.status_code)
            self.assertEqual(120, res.json["data"]["utc_offset_minutes"])
        self._run(go())


# ── /api/time ─────────────────────────────────────────────────────────────────

class TestTimeRoute(AsyncCase):

    def test_not_supported_on_cpython(self):
        async def go():
            client, _ = _build_client()
            res = await client.post("/api/time", body={
                "year": 2026, "month": 7, "day": 3,
                "hour": 12, "minute": 0, "second": 0,
            })
            self.assertEqual(501, res.status_code)
        self._run(go())

    def test_missing_field_returns_400(self):
        async def go():
            client, _ = _build_client()
            res = await client.post("/api/time", body={"year": 2026})
            self.assertEqual(400, res.status_code)
        self._run(go())

    def test_invalid_date_returns_400(self):
        async def go():
            client, _ = _build_client()
            res = await client.post("/api/time", body={
                "year": 2026, "month": 2, "day": 30,
                "hour": 12, "minute": 0, "second": 0,
            })
            self.assertEqual(400, res.status_code)
        self._run(go())

    def test_year_below_2013_returns_400(self):
        async def go():
            client, _ = _build_client()
            res = await client.post("/api/time", body={
                "year": 2000, "month": 1, "day": 1,
                "hour": 0, "minute": 0, "second": 0,
            })
            self.assertEqual(400, res.status_code)
        self._run(go())


# ── /api/schedules/upcoming ───────────────────────────────────────────────────

class TestUpcomingRoute(AsyncCase):

    async def _client_with_daily_schedule(self):
        client, _ = _build_client()
        ep = (await client.post("/api/endpoints", body=_EP_BODY)).json["data"]
        body = dict(_SCHEDULE_BODY)
        body["target_id"] = ep["id"]
        created = await client.post("/api/schedules", body=body)
        assert created.status_code == 201
        return client, created.json["data"]

    def test_daily_schedule_appears(self):
        async def go():
            client, sch = await self._client_with_daily_schedule()
            res = await client.get("/api/schedules/upcoming?days=3")
            self.assertEqual(200, res.status_code)
            events = res.json["data"]["events"]
            self.assertTrue(events)
            self.assertEqual(sch["id"], events[0]["schedule_id"])
            self.assertRegex(events[0]["local_time"], r"^\d{2}:\d{2}$")
            self.assertRegex(events[0]["local_date"], r"^\d{4}-\d{2}-\d{2}$")
            self.assertGreater(events[0]["in_minutes"], 0)
        self._run(go())

    def test_disabled_schedule_excluded(self):
        async def go():
            client, sch = await self._client_with_daily_schedule()
            await client.patch(
                f"/api/schedules/{sch['id']}/enabled", body={"enabled": False}
            )
            res = await client.get("/api/schedules/upcoming?days=3")
            self.assertEqual([], res.json["data"]["events"])
        self._run(go())

    def test_days_out_of_range_returns_400(self):
        async def go():
            client, _ = _build_client()
            res = await client.get("/api/schedules/upcoming?days=30")
            self.assertEqual(400, res.status_code)
        self._run(go())

    def test_days_not_integer_returns_400(self):
        async def go():
            client, _ = _build_client()
            res = await client.get("/api/schedules/upcoming?days=abc")
            self.assertEqual(400, res.status_code)
        self._run(go())


# ── Referential integrity on delete ───────────────────────────────────────────

class TestDeleteConflicts(AsyncCase):

    def test_delete_zone_with_endpoint_returns_409(self):
        async def go():
            client, _ = _build_client()
            zone = (await client.post("/api/zones", body=_ZONE_BODY)).json["data"]
            await client.post(
                "/api/endpoints", body={"name": "אור", "zone_id": zone["id"]}
            )
            res = await client.delete(f"/api/zones/{zone['id']}")
            self.assertEqual(409, res.status_code)
            self.assertIn("אור", res.json["error"])
        self._run(go())

    def test_delete_endpoint_in_group_returns_409(self):
        async def go():
            client, _ = _build_client()
            ep = (await client.post("/api/endpoints", body=_EP_BODY)).json["data"]
            await client.post(
                "/api/groups", body={"name": "קבוצה", "member_ids": [ep["id"]]}
            )
            res = await client.delete(f"/api/endpoints/{ep['id']}")
            self.assertEqual(409, res.status_code)
        self._run(go())

    def test_delete_endpoint_with_schedule_returns_409(self):
        async def go():
            client, _ = _build_client()
            ep = (await client.post("/api/endpoints", body=_EP_BODY)).json["data"]
            body = dict(_SCHEDULE_BODY)
            body["target_id"] = ep["id"]
            await client.post("/api/schedules", body=body)
            res = await client.delete(f"/api/endpoints/{ep['id']}")
            self.assertEqual(409, res.status_code)
        self._run(go())

    def test_delete_group_with_schedule_returns_409(self):
        async def go():
            client, _ = _build_client()
            grp = (await client.post("/api/groups", body=_GROUP_BODY)).json["data"]
            body = dict(_SCHEDULE_BODY)
            body["target_type"] = "group"
            body["target_id"] = grp["id"]
            await client.post("/api/schedules", body=body)
            res = await client.delete(f"/api/groups/{grp['id']}")
            self.assertEqual(409, res.status_code)
        self._run(go())

    def test_delete_unreferenced_endpoint_succeeds(self):
        async def go():
            client, _ = _build_client()
            ep = (await client.post("/api/endpoints", body=_EP_BODY)).json["data"]
            res = await client.delete(f"/api/endpoints/{ep['id']}")
            self.assertEqual(200, res.status_code)
        self._run(go())


# ── Name required for entities ────────────────────────────────────────────────

class TestNameRequired(AsyncCase):

    def test_zone_without_name_returns_400(self):
        async def go():
            client, _ = _build_client()
            res = await client.post("/api/zones", body={})
            self.assertEqual(400, res.status_code)
            self.assertFalse(res.json["ok"])
        self._run(go())

    def test_zone_empty_name_returns_400(self):
        async def go():
            client, _ = _build_client()
            res = await client.post("/api/zones", body={"name": "   "})
            self.assertEqual(400, res.status_code)
        self._run(go())

    def test_endpoint_without_name_returns_400(self):
        async def go():
            client, _ = _build_client()
            res = await client.post("/api/endpoints", body={})
            self.assertEqual(400, res.status_code)
        self._run(go())

    def test_group_without_name_returns_400(self):
        async def go():
            client, _ = _build_client()
            res = await client.post("/api/groups", body={})
            self.assertEqual(400, res.status_code)
        self._run(go())

    def test_update_zone_to_empty_name_returns_400(self):
        async def go():
            client, _ = _build_client()
            z = (await client.post("/api/zones", body={"name": "סלון"})).json["data"]
            res = await client.put(f"/api/zones/{z['id']}", body={"name": ""})
            self.assertEqual(400, res.status_code)
        self._run(go())


class GcPolicyTests(unittest.TestCase):
    """Whether a response is followed by gc.collect() is a product decision.

    It used to be decided by hasattr(gc, "mem_free") -- true on BOTH boards,
    so the switch could not tell product A (where a collect mid-render can
    free a partial draw buffer: LoadProhibited boot loop) from product B
    (where collecting is what keeps a no-PSRAM heap usable). The panel was
    saved only by not building an app at all, while brain.py documents
    create_app as its intended future channel.

    These run on CPython, where the old platform default was always False --
    so this branch had no test coverage at all until the flag made it
    reachable.
    """

    def _app(self, **kwargs):
        repo     = MemoryRepository()
        executor = Executor(H2Simulator(["sent_to_zigbee"]), MemoryEventJournal())
        return create_app(CrudService(repo),
                          ControlService(executor, repo),
                          SettingsStore(_temp_settings_path()),
                          repo, **kwargs)

    def test_product_a_can_refuse_the_collect(self):
        self.assertEqual([], self._app(collect_after_request=False)
                         .after_request_handlers)

    def test_product_b_can_ask_for_the_collect(self):
        self.assertEqual(1, len(self._app(collect_after_request=True)
                                .after_request_handlers))

    def test_default_is_unchanged_platform_behaviour(self):
        # None keeps the historical default so no existing caller moved.
        from smart_kosher.web.server import _IS_MICROPYTHON
        expected = 1 if _IS_MICROPYTHON else 0
        self.assertEqual(expected, len(self._app().after_request_handlers))


if __name__ == "__main__":
    unittest.main()
