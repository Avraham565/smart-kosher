"""The packaged city list, checked as data rather than through a screen.

A user picks the city nearest them and everything downstream -- every zman,
every schedule that fires on one -- comes from the three numbers behind that
name. A wrong coordinate or a stale elevation here is invisible in the UI and
wrong forever, so the list is checked here instead.
"""

import unittest

from smart_kosher.data import get_city, load_cities, resolve_city, search_cities
from smart_kosher.zmanim import compute_zmanim

# Israel, generously bounded. A transposed or mistyped coordinate leaves it.
LAT_RANGE = (29.4, 33.4)
LON_RANGE = (34.2, 35.95)

EXPECTED_CITY_COUNT = 40


class CityDataTests(unittest.TestCase):
    def setUp(self):
        self.cities = load_cities()

    def test_the_list_is_the_agreed_size(self):
        self.assertEqual(EXPECTED_CITY_COUNT, len(self.cities))

    def test_every_city_carries_geography_and_nothing_else(self):
        for city_id, city in self.cities.items():
            with self.subTest(city=city_id):
                self.assertEqual({"name_he", "lat", "lon", "elevation"}, set(city))

    def test_every_coordinate_falls_inside_israel(self):
        for city_id, city in self.cities.items():
            with self.subTest(city=city_id):
                self.assertGreaterEqual(city["lat"], LAT_RANGE[0])
                self.assertLessEqual(city["lat"], LAT_RANGE[1])
                self.assertGreaterEqual(city["lon"], LON_RANGE[0])
                self.assertLessEqual(city["lon"], LON_RANGE[1])

    def test_no_elevation_is_below_sea_level_or_absurd(self):
        # Negative is rejected upstream by the reference library, and Israel's
        # highest inhabited ground is well under 1,200 m.
        for city_id, city in self.cities.items():
            with self.subTest(city=city_id):
                self.assertGreaterEqual(city["elevation"], 0)
                self.assertLess(city["elevation"], 1200)

    def test_names_and_ids_are_unique(self):
        names = [city["name_he"] for city in self.cities.values()]
        self.assertEqual(len(names), len(set(names)))

    def test_no_two_cities_are_the_same_place(self):
        # Distinct entries the user must choose between. Anything under a
        # kilometre is a duplicate wearing two names.
        entries = list(self.cities.items())
        for index, (city_id, city) in enumerate(entries):
            for other_id, other in entries[index + 1:]:
                km = (((city["lat"] - other["lat"]) * 111.0) ** 2
                      + ((city["lon"] - other["lon"]) * 94.0) ** 2) ** 0.5
                with self.subTest(pair=(city_id, other_id)):
                    self.assertGreater(km, 1.0)

    def test_the_country_is_actually_covered(self):
        # The point of forty entries: someone in Eilat and someone in Nahariya
        # both find a city near them. A list that drifted into one metro area
        # would still pass every check above.
        lats = [city["lat"] for city in self.cities.values()]
        self.assertLess(min(lats), 30.0, "nothing in the far south")
        self.assertGreater(max(lats), 32.9, "nothing in the far north")

        elevations = [city["elevation"] for city in self.cities.values()]
        self.assertEqual(0, min(elevations), "no sea-level city")
        self.assertGreater(max(elevations), 700, "no mountain city")


class CityZmanimTests(unittest.TestCase):
    """Every city must produce a usable day, not just valid-looking numbers."""

    def test_every_city_computes_a_coherent_day(self):
        for city_id, city in load_cities().items():
            for month, day in ((1, 15), (6, 21), (9, 22), (12, 21)):
                with self.subTest(city=city_id, date=(month, day)):
                    z = compute_zmanim(2026, month, day,
                                       city["lat"], city["lon"], city["elevation"])

                    self.assertIsNotNone(z["netz_hachama"])
                    self.assertLess(z["alot_hashachar"], z["netz_hachama"])
                    self.assertLess(z["netz_hachama"], z["sof_zman_shema_gra"])
                    self.assertLess(z["sof_zman_shema_gra"], z["chatzot_hayom"])
                    self.assertLess(z["chatzot_hayom"], z["mincha_ketana"])
                    self.assertLess(z["mincha_ketana"], z["shkia"])
                    self.assertLess(z["candle_lighting"], z["shkia"])
                    self.assertLess(z["shkia"], z["tset_hakohavim"])
                    self.assertLess(z["tset_hakohavim"],
                                    z["tset_hakohavim_rabeinu_tam"])
                    self.assertLess(z["shkia"], z["chatzot_halayla"])

    def test_elevation_reaches_the_zmanim_for_every_city(self):
        # The regression that started this: elevation sat in cities.json and
        # nothing passed it on. A mountain city must not compute a sea-level
        # sunset, and a coastal one must be unmoved.
        for city_id, city in load_cities().items():
            with self.subTest(city=city_id):
                at_sea = compute_zmanim(2026, 6, 21, city["lat"], city["lon"], 0)
                actual = compute_zmanim(2026, 6, 21, city["lat"], city["lon"],
                                        city["elevation"])
                if city["elevation"] >= 400:
                    self.assertGreater(actual["shkia"] - at_sea["shkia"], 3.0)
                elif city["elevation"] == 0:
                    self.assertEqual(at_sea["shkia"], actual["shkia"])

    def test_north_and_south_disagree_the_way_geography_says(self):
        # A list where every city quietly shared one coordinate would pass the
        # per-city checks; this one needs them to actually differ.
        eilat = get_city("eilat")
        nahariya = get_city("nahariya")
        summer_day = []
        for city in (eilat, nahariya):
            z = compute_zmanim(2026, 6, 21, city["lat"], city["lon"], city["elevation"])
            summer_day.append(z["shkia"] - z["netz_hachama"])
        # Longer summer daylight the further north you stand. Israel spans 3.4
        # degrees of latitude, which is worth about 16 minutes of solstice
        # daylight; 12 clears the real margin without pinning the exact figure.
        self.assertGreater(summer_day[1], summer_day[0] + 12)


class CitySearchTests(unittest.TestCase):
    """The panel picks a city by typing, because the RGB panel cannot scroll a
    forty-item list. Two letters have to be enough."""

    def _names(self, query, **kw):
        return [c["name_he"] for c in search_cities(query, **kw)]

    def test_empty_query_returns_the_whole_list_sorted(self):
        names = self._names("")
        self.assertEqual(EXPECTED_CITY_COUNT, len(names))
        self.assertEqual(sorted(names), names)

    def test_finds_by_the_start_of_the_name(self):
        self.assertIn("ירושלים", self._names("ירו"))
        self.assertIn("נהריה", self._names("נהר"))

    def test_finds_by_any_word_of_the_name(self):
        # Somebody looking for בני ברק is as likely to start typing ברק.
        self.assertIn("בני ברק", self._names("ברק"))
        self.assertIn("תל אביב", self._names("אביב"))
        self.assertIn("קרית גת", self._names("גת"))
        self.assertIn("בית שמש", self._names("שמש"))

    def test_a_leading_word_match_outranks_a_later_one(self):
        # "בית" must not put בית שאן below a city that merely contains the word.
        names = self._names("בית")
        self.assertTrue(names[0].startswith("בית"), names)

    def test_two_letters_narrow_the_country_to_a_handful(self):
        # The claim the whole picker rests on: after two letters the matches fit
        # on screen without scrolling.
        for query in ("ירו", "תל", "בא", "חי", "צפ", "אש", "רח", "טב"):
            with self.subTest(query=query):
                self.assertLessEqual(len(self._names(query)), 6)

    def test_every_city_is_reachable_by_typing_its_own_name(self):
        # A city nobody can type is a city nobody can select.
        for city_id, city in load_cities().items():
            name = city["name_he"]
            with self.subTest(city=city_id):
                self.assertIn(name, self._names(name))
                self.assertIn(name, self._names(name[:2]))

    def test_every_city_is_reachable_within_four_results(self):
        # The panel shows four slots. Every city must surface inside them for
        # some prefix of its own name, or it cannot be picked at all.
        for city_id, city in load_cities().items():
            name = city["name_he"]
            with self.subTest(city=city_id):
                for length in range(2, len(name) + 1):
                    top = self._names(name[:length], limit=4)
                    if name in top:
                        break
                else:
                    self.fail("{} never reaches the top four".format(name))

    def test_unknown_text_matches_nothing(self):
        self.assertEqual([], self._names("קקק"))

    def test_query_is_trimmed_and_survives_bad_input(self):
        self.assertIn("ירושלים", self._names("  ירו  "))
        for value in (None, 5, {}):
            with self.subTest(value=value):
                self.assertEqual(EXPECTED_CITY_COUNT, len(search_cities(value)))

    def test_limit_caps_the_result_list(self):
        self.assertEqual(4, len(search_cities("", limit=4)))
        self.assertEqual(0, len(search_cities("", limit=0)))

    def test_results_carry_the_id_the_api_expects(self):
        for entry in search_cities("ירו"):
            self.assertEqual({"id", "name_he", "lat", "lon", "elevation"},
                             set(entry))
            self.assertIsNotNone(resolve_city(entry["id"]))


class CityResolutionTests(unittest.TestCase):
    """Picking a city is picking a location; both spellings must land there."""

    def test_resolves_by_id(self):
        city_id, city = resolve_city("jerusalem")
        self.assertEqual("jerusalem", city_id)
        self.assertEqual("ירושלים", city["name_he"])

    def test_resolves_by_hebrew_name(self):
        # What a settings file written before the picker holds.
        city_id, _ = resolve_city("ירושלים")
        self.assertEqual("jerusalem", city_id)

    def test_both_spellings_resolve_to_the_same_profile(self):
        for city_id, city in load_cities().items():
            with self.subTest(city=city_id):
                self.assertEqual(resolve_city(city_id), resolve_city(city["name_he"]))

    def test_unknown_and_malformed_names_resolve_to_nothing(self):
        for value in ("", "   ", "nowhere", None, 5, {}):
            with self.subTest(value=value):
                self.assertIsNone(resolve_city(value))


if __name__ == "__main__":
    unittest.main()
