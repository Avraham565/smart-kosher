import unittest
from datetime import date, timedelta

from smart_kosher.data import get_city, load_cities
import smart_kosher.zmanim.hebrew_cal as hebrew_cal
from smart_kosher.zmanim import (
    compute_zmanim,
    date_info,
    gregorian_to_jewish,
    israel_dst_dates,
    israel_utc_offset_for_local,
    jewish_to_gregorian,
    parasha,
)


class ZmanimTests(unittest.TestCase):
    def test_known_jerusalem_date(self):
        info = date_info(2026, 6, 5)
        self.assertEqual((5786, 3, 20), (info["j_year"], info["j_month"], info["j_day"]))
        self.assertEqual(6, info["dow"])

        values = compute_zmanim(2026, 6, 5, 31.7683, 35.2137, 754, 40, 40)
        self.assertLess(values["netz_hachama"], values["chatzot_hayom"])
        self.assertLess(values["chatzot_hayom"], values["shkia"])
        self.assertAlmostEqual(
            values["tset_hakohavim_shabbat"] - values["shkia"], 40, places=6
        )
        self.assertAlmostEqual(218.4333, compute_zmanim(
            2024, 3, 20, 31.7683, 35.2137, 754
        )["netz_hachama"], delta=0.05)

    def test_city_specific_tzais_offset_is_used(self):
        values = compute_zmanim(2026, 6, 5, 32.0853, 34.7818, 0, 18, 42)
        self.assertAlmostEqual(
            values["tset_hakohavim_shabbat"] - values["shkia"], 42, places=6
        )

    def test_round_trip_every_day_in_supported_software_range(self):
        current = date(2024, 1, 1)
        end = date(2040, 12, 31)
        while current <= end:
            jewish = gregorian_to_jewish(current.year, current.month, current.day)
            self.assertEqual(
                (current.year, current.month, current.day),
                jewish_to_gregorian(*jewish),
            )
            current += timedelta(days=1)

    def test_all_city_profiles_compute_consistent_times(self):
        cities = load_cities()
        self.assertGreater(len(cities), 0)
        for city_id, city in cities.items():
            with self.subTest(city=city_id):
                values = compute_zmanim(
                    2026, 6, 5,
                    city["lat"], city["lon"], city["elevation"],
                    city["candle_offset"], city["tzais_offset"],
                )
                self.assertLess(values["candle_lighting"], values["shkia"])
                self.assertAlmostEqual(
                    city["tzais_offset"],
                    values["tset_hakohavim_shabbat"] - values["shkia"],
                    places=6,
                )

    def test_city_loader_returns_defensive_copies(self):
        city = get_city("jerusalem")
        self.assertEqual("ירושלים", city["name_he"])
        city["lat"] = 0
        self.assertEqual(31.7683, get_city("jerusalem")["lat"])
        with self.assertRaises(KeyError):
            get_city("unknown")

    def test_known_parasha(self):
        self.assertEqual(("vayikra",), parasha(2024, 3, 20, in_israel=True))
        self.assertEqual(("devarim",), parasha(2024, 8, 9, in_israel=True))

    def test_invalid_dates_and_locations_are_rejected(self):
        with self.assertRaises(ValueError):
            gregorian_to_jewish(2026, 2, 31)
        with self.assertRaises(ValueError):
            jewish_to_gregorian(5786, 2, 31)
        with self.assertRaises(ValueError):
            compute_zmanim(2026, 1, 1, 91, 35)
        with self.assertRaises(ValueError):
            compute_zmanim(2026, 1, 1, 31, 181)
        with self.assertRaises(ValueError):
            compute_zmanim(2026, 1, 1, 31, 35, candle_offset=-1)

    def test_israel_dst_boundaries(self):
        start, end = israel_dst_dates(2026)
        self.assertEqual((2026, 3, 27), start)
        self.assertEqual((2026, 10, 25), end)
        self.assertEqual(120, israel_utc_offset_for_local(2026, 3, 27, 1, 59))
        with self.assertRaises(ValueError):
            israel_utc_offset_for_local(2026, 3, 27, 2, 0)
        self.assertEqual(180, israel_utc_offset_for_local(2026, 3, 27, 3, 0))
        self.assertEqual(180, israel_utc_offset_for_local(2026, 10, 25, 1, 30))
        self.assertEqual(120, israel_utc_offset_for_local(2026, 10, 25, 2, 0))

    def test_calendar_caches_are_bounded(self):
        for year in range(5000, 5100):
            hebrew_cal.days_in_jewish_year(year)
            hebrew_cal.sorted_months_in_jewish_year(year)
        self.assertLessEqual(len(hebrew_cal._cache_elapsed), hebrew_cal._CACHE_LIMIT)
        self.assertLessEqual(len(hebrew_cal._cache_year_days), hebrew_cal._CACHE_LIMIT)
        self.assertLessEqual(len(hebrew_cal._cache_months), hebrew_cal._CACHE_LIMIT)


if __name__ == "__main__":
    unittest.main()
