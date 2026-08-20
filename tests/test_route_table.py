"""The REST surface has one source, and both ends really read it.

`web/route_table.ROUTES` replaced two hand-maintained copies of the same
mapping -- the hub's microdot registration and the desktop client's
`rest_to_op`. The point of that change is only kept if neither end quietly
grows a route of its own again, so these tests assert the property directly:
every route in the table is registered by the hub, and every route in the
table is resolvable by the client.

That is a stronger check than comparing the two implementations to each
other, which is what a test written before the refactor would have had to do.

The client is loaded from its file rather than by putting `apps/desktop/` on
`sys.path`: `apps/desktop/bridge.py` and `products/panel/device/bridge.py` are
two different modules both named `bridge`, and `tests/test_panel_scheduler.py`
already puts the panel's device directory on the path. Two directories
competing for one module name works
only until something imports the other one first, and then it fails by test
ordering -- so this binds the file directly, under a name of its own.
"""

import asyncio
import importlib.util
import unittest
from pathlib import Path

from smart_kosher.web.route_table import BODY_METHODS, HTTP_STATUS, ROUTES, resolve

ROOT = Path(__file__).resolve().parents[1]


def _load_client_bridge():
    spec = importlib.util.spec_from_file_location(
        "client_bridge", ROOT / "apps" / "desktop" / "bridge.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rest_to_op = _load_client_bridge().rest_to_op


def _sample_path(route):
    """A concrete URL for a route pattern, with the placeholders filled in."""
    parts = [
        "sample_id" if part[:1] == "<" else part
        for part in route.parts
    ]
    return "/" + "/".join(parts)


class RouteTableTests(unittest.TestCase):
    def test_table_is_not_empty(self):
        # 11 fixed routes + 4 CRUD verbs x 4 entities.
        self.assertEqual(27, len(ROUTES))

    def test_every_route_is_unique(self):
        seen = [(route.method, route.pattern) for route in ROUTES]
        self.assertEqual(len(seen), len(set(seen)))

    def test_every_op_name_is_dotted(self):
        for route in ROUTES:
            with self.subTest(op=route.op):
                self.assertIn(".", route.op)

    def test_only_body_methods_want_a_body(self):
        for route in ROUTES:
            with self.subTest(route=route.pattern):
                self.assertEqual(route.method in BODY_METHODS,
                                 route.wants_body())

    def test_kind_map_covers_every_api_error_kind(self):
        from smart_kosher.application import api
        kinds = {api.BAD_REQUEST, api.NOT_FOUND, api.CONFLICT,
                 api.UNSUPPORTED, api.INTERNAL}
        self.assertEqual(kinds, set(HTTP_STATUS))


class HubRegistersEveryRouteTests(unittest.TestCase):
    """The hub side derives from the table."""

    def setUp(self):
        from smart_kosher.adapters import (
            H2Simulator,
            MemoryEventJournal,
            MemoryRepository,
        )
        from smart_kosher.application.control_service import ControlService
        from smart_kosher.application.crud_service import CrudService
        from smart_kosher.application.executor import Executor
        from smart_kosher.web.server import create_app

        repo = MemoryRepository()
        executor = Executor(H2Simulator(), MemoryEventJournal())

        class _Settings:
            def get(self):
                return {}

            def update(self, patch):
                pass

        self.app = create_app(CrudService(repo), ControlService(executor, repo),
                              _Settings(), repository=repo)

    def test_microdot_url_map_matches_the_table(self):
        registered = set()
        for methods, pattern, _handler, _a, _b in self.app.url_map:
            for method in methods:
                registered.add((method, pattern.url_pattern))
        expected = set((route.method, route.pattern) for route in ROUTES)
        self.assertEqual(expected, registered)


class ClientResolvesEveryRouteTests(unittest.TestCase):
    """The client side derives from the same table."""

    def test_rest_to_op_resolves_every_route(self):
        for route in ROUTES:
            with self.subTest(route="{} {}".format(route.method, route.pattern)):
                translated = rest_to_op(
                    route.method, _sample_path(route), {}, {})
                self.assertIsNotNone(translated)
                self.assertEqual(route.op, translated[0])
                self.assertEqual(route.created, translated[2])

    def test_unknown_path_is_not_translated(self):
        self.assertIsNone(rest_to_op("GET", "/api/nope", {}, None))
        self.assertIsNone(rest_to_op("DELETE", "/api/settings", {}, None))
        self.assertIsNone(rest_to_op("GET", "/", {}, None))

    def test_query_values_are_flattened_out_of_parse_qs_lists(self):
        # parse_qs hands back a list per key; the table works in single values.
        op, params, _ = rest_to_op(
            "GET", "/api/schedules/upcoming", {"days": ["5"]}, None)
        self.assertEqual(("schedules.upcoming", {"days": 5}), (op, params))

    def test_missing_days_falls_back_to_three(self):
        _, params, _ = rest_to_op("GET", "/api/schedules/upcoming", {}, None)
        self.assertEqual({"days": 3}, params)

    def test_non_numeric_days_is_passed_through_for_the_hub_to_reject(self):
        # Not rejected locally: Api owns that message, and producing it in two
        # places is how the two ends drifted apart before.
        _, params, _ = rest_to_op(
            "GET", "/api/schedules/upcoming", {"days": ["abc"]}, None)
        self.assertEqual({"days": "abc"}, params)

    def test_path_variables_reach_the_params(self):
        _, params, _ = rest_to_op("DELETE", "/api/zones/z_42", {}, None)
        self.assertEqual({"id": "z_42"}, params)

        _, params, _ = rest_to_op(
            "PATCH", "/api/schedules/sch_7/enabled", {}, {"enabled": False})
        self.assertEqual({"id": "sch_7", "enabled": False}, params)


class ResolveTests(unittest.TestCase):
    def test_fixed_path_wins_over_a_parameterised_one(self):
        route, _ = resolve("GET", "/api/schedules/upcoming")
        self.assertEqual("schedules.upcoming", route.op)

    def test_method_is_part_of_the_match(self):
        self.assertEqual("zones.list", resolve("GET", "/api/zones")[0].op)
        self.assertEqual("zones.create", resolve("POST", "/api/zones")[0].op)

    def test_slashes_are_matched_the_way_the_hub_matches_them(self):
        """Deliberately replaces a test that pinned the opposite.

        The old test asserted that "/api/status/" and "//api//status" resolve
        here. They do not resolve over HTTP -- Microdot splits the pattern with
        lstrip('/').split('/') and compares segment counts -- so what that test
        pinned was one side of exactly the divergence this table exists to
        prevent. A test can document one half of an inconsistency; it cannot
        settle which half is right.

        Strict is the side that changes nothing that works. No caller sends
        these paths: the desktop UI's "/api/zones/" strings are prefixes it
        concatenates an id onto, and every other client builds its URLs from
        this table. HTTP has been strict since it shipped, and it is the
        transport with clients outside this repo. Making the table agree with
        it moves the seam without moving any behaviour anyone depends on.
        """
        self.assertEqual((None, None), resolve("GET", "/api/status/"))
        self.assertEqual((None, None), resolve("GET", "//api//status"))
        self.assertEqual("status.get", resolve("GET", "/api/status")[0].op)


class TransportParityTests(unittest.TestCase):
    """The property the table was created for, asserted as behaviour.

    Comparing the two registrations as strings is what the earlier tests did,
    and it is why the divergence survived: both ends really did read every row
    of the table, and still answered the same request differently. What the
    table promises is not "the same patterns" but "the same request behaves
    identically whether it arrives over WiFi or over USB", so that is what is
    checked here -- one request, both transports, same status code.
    """

    CASES = [
        # (method, path, body, why)
        ("GET", "/api/status", None, "the plain case"),
        ("GET", "/api/status/", None, "trailing slash: 404 on both"),
        ("GET", "//api//status", None, "doubled slashes: 404 on both"),
        ("GET", "/api/nope", None, "unknown path"),
        ("GET", "/api/zones", None, "a list"),
        ("GET", "/api/settings", None, "settings read"),
        ("PUT", "/api/settings", None, "no body: {} on both, not a 400 here "
                                       "and a silent no-op there"),
        ("PUT", "/api/settings", {}, "an explicitly empty body"),
        ("PUT", "/api/settings", {"in_israel": False}, "a real update"),
        ("PUT", "/api/settings", {"nope": 1}, "an unknown key is rejected"),
        ("GET", "/api/schedules/upcoming", None, "a query-string route"),
        ("DELETE", "/api/zones/z_missing", None, "not found"),
    ]

    @staticmethod
    def _build():
        from smart_kosher.adapters import (
            H2Simulator,
            MemoryEventJournal,
            MemoryRepository,
        )
        from smart_kosher.application.api import Api
        from smart_kosher.application.control_service import ControlService
        from smart_kosher.application.crud_service import CrudService
        from smart_kosher.application.device_time import DeviceTimeService
        from smart_kosher.application.executor import Executor
        from smart_kosher.application.views import ViewService
        from smart_kosher.web.server import create_app

        repo = MemoryRepository()
        executor = Executor(H2Simulator(), MemoryEventJournal())

        class _Settings:
            def __init__(self):
                self._values = {"utc_offset_minutes": 120, "in_israel": True}
                self.load_error = None

            def get(self):
                return dict(self._values)

            def update(self, patch):
                self._values.update(patch)

        # One Api behind both transports, so a difference can only come from
        # the transport translation -- which is the only thing under test.
        api = Api(CrudService(repo), ControlService(executor, repo),
                  _Settings(), views=ViewService(repo),
                  device_time=DeviceTimeService(None))
        app = create_app(None, None, None, api=api,
                         collect_after_request=False)
        return app, api

    @staticmethod
    def _http_status(app, method, path, body):
        from microdot.test_client import TestClient

        async def go():
            client = TestClient(app)
            kwargs = {} if body is None else {"body": body}
            res = await client.request(method, path, **kwargs)
            return res.status_code

        return asyncio.run(go())

    @staticmethod
    def _usb_status(api, method, path, body):
        """What apps/desktop/bridge.py:request would answer, same mapping."""
        from smart_kosher.application.api import ApiError

        translated = rest_to_op(method, path, {}, body)
        if translated is None:
            return 404
        op, params, created = translated
        try:
            asyncio.run(api.dispatch(op, params))
        except ApiError as exc:
            return HTTP_STATUS.get(exc.kind, 500)
        return 201 if created else 200

    def test_a_known_method_mismatch_divergence_is_recorded_not_hidden(self):
        """One difference this test found and this task did not close.

        A path that exists with a different method is 405 over HTTP, because
        Microdot answers method-not-allowed out of its own routing table, and
        404 over USB, because resolve() filters on method and simply finds
        nothing. 405 is the better answer -- the resource is there, the verb is
        not -- but teaching the USB side to tell the two apart means changing
        apps/desktop/bridge.py, which task 23 does not put in scope.

        Pinned rather than dropped from the case list above, so it stays
        visible. If someone closes it, this test fails and says so.
        """
        http_app, _ = self._build()
        _, usb_api = self._build()
        self.assertEqual(405, self._http_status(http_app, "DELETE",
                                                "/api/settings", None))
        self.assertEqual(404, self._usb_status(usb_api, "DELETE",
                                               "/api/settings", None))

    def test_both_transports_answer_every_request_the_same_way(self):
        for method, path, body, why in self.CASES:
            with self.subTest(request="{} {}".format(method, path), why=why):
                http_app, _ = self._build()
                _, usb_api = self._build()
                self.assertEqual(
                    self._http_status(http_app, method, path, body),
                    self._usb_status(usb_api, method, path, body),
                    "{} {} answers differently over HTTP than over USB "
                    "({})".format(method, path, why))


if __name__ == "__main__":
    unittest.main()
