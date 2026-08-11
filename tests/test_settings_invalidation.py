"""Changing the location must change the zmanim, immediately.

ViewService and the scheduler both hold a Planner across requests, because
building one runs a full zmanim computation and it caches a day of results.
They rebuild it when ``settings_key`` changes. That key is what makes picking a
city work at all -- if it ever stops covering a field the zmanim depend on, the
device keeps serving the previous city's times and nothing reports a problem.

Nothing pinned that contract until this file. It is easy to break by accident:
``elevation`` became a setting only when the picker was added, and the key is
built by exclusion (everything except ``device_time``), so a future exclusion
is all it would take.
"""

import unittest

from smart_kosher.adapters import MemoryRepository
from smart_kosher.application.views import (
    SETTINGS_DEFAULTS,
    ViewService,
    planner_config,
    settings_key,
)
from smart_kosher.data import get_city

# Every field of the settings that moves a zman, and a value that really does
# move it. Deliberately not derived from SETTINGS_DEFAULTS: the point is to
# state independently what must matter.
LOCATION_FIELDS = ("lat", "lon", "elevation")


def _settings(**overrides):
    base = dict(SETTINGS_DEFAULTS)
    base["city"] = "ירושלים"
    base.update(overrides)
    return base


class SettingsKeyTests(unittest.TestCase):
    def test_key_covers_every_field_the_zmanim_depend_on(self):
        base = _settings()
        for field, moved in (("lat", 32.8), ("lon", 34.99), ("elevation", 0),
                             ("utc_offset_minutes", 180), ("in_israel", False)):
            with self.subTest(field=field):
                self.assertNotEqual(
                    settings_key(base), settings_key(_settings(**{field: moved})),
                    "{} does not change the planning key".format(field))

    def test_key_ignores_the_clock(self):
        # device_time changes every second; keying on it would rebuild the
        # planner constantly and throw away the cache it exists for.
        self.assertEqual(
            settings_key(_settings(device_time="2026-01-01 00:00:00")),
            settings_key(_settings(device_time="2026-08-11 21:00:00")))


class PlannerRebuildTests(unittest.TestCase):
    def setUp(self):
        self.views = ViewService(MemoryRepository())

    def _shkia(self, settings):
        return self.views.today_view(settings, 2026, 8, 14)["zmanim"]["shkia"]

    def test_switching_city_moves_the_computed_zmanim(self):
        jerusalem = _settings()
        eilat_city = get_city("eilat")
        eilat = _settings(city="אילת", lat=eilat_city["lat"],
                          lon=eilat_city["lon"],
                          elevation=eilat_city["elevation"])

        first = self._shkia(jerusalem)
        second = self._shkia(eilat)
        self.assertNotEqual(first, second, "the planner served a stale city")

        # And back again -- the cache must not be one-way.
        self.assertEqual(first, self._shkia(jerusalem))

    def test_elevation_alone_moves_the_computed_zmanim(self):
        # The narrowest case, and the one that regressed before: same city,
        # same coordinates, only the altitude wired through.
        sea = self._shkia(_settings(elevation=0))
        high = self._shkia(_settings(elevation=779))
        self.assertNotEqual(sea, high)

    def test_planner_config_carries_the_elevation(self):
        config = planner_config(_settings(elevation=779))
        self.assertEqual(779, config.altitude)


if __name__ == "__main__":
    unittest.main()
