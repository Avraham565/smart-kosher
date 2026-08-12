"""The REST surface has one source, and both ends really read it.

`web/route_table.ROUTES` replaced two hand-maintained copies of the same
mapping -- the hub's microdot registration and the desktop client's
`rest_to_op`. The point of that change is only kept if neither end quietly
grows a route of its own again, so these tests assert the property directly:
every route in the table is registered by the hub, and every route in the
table is resolvable by the client.

That is a stronger check than comparing the two implementations to each
other, which is what a test written before the refactor would have had to do.

The client is loaded from its file rather than by putting `client/` on
`sys.path`: `client/bridge.py` and `panel_mp/bridge.py` are two different
modules both named `bridge`, and `tests/test_panel_scheduler.py` already puts
`panel_mp/` on the path. Two directories competing for one module name works
only until something imports the other one first, and then it fails by test
ordering -- so this binds the file directly, under a name of its own.
"""

import importlib.util
import unittest
from pathlib import Path

from smart_kosher.web.route_table import BODY_METHODS, HTTP_STATUS, ROUTES, resolve

ROOT = Path(__file__).resolve().parents[1]


def _load_client_bridge():
    spec = importlib.util.spec_from_file_location(
        "client_bridge", ROOT / "client" / "bridge.py")
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

    def test_trailing_and_duplicate_slashes_are_tolerated(self):
        self.assertEqual("status.get", resolve("GET", "/api/status/")[0].op)
        self.assertEqual("status.get", resolve("GET", "//api//status")[0].op)


if __name__ == "__main__":
    unittest.main()
