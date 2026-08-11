import unittest
from datetime import date, timedelta

import smart_kosher.zmanim.hebrew_cal as hebrew_cal
from smart_kosher.data import get_city, load_cities
from smart_kosher.zmanim import (
    CANDLE_OFFSET_MINUTES,
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

        values = compute_zmanim(2026, 6, 5, 31.7683, 35.2137, 779)
        self.assertLess(values["netz_hachama"], values["chatzot_hayom"])
        self.assertLess(values["chatzot_hayom"], values["shkia"])
        self.assertLess(values["shkia"], values["tset_hakohavim_shabbat"])

    def test_shabbat_exit_is_an_angle_not_a_fixed_offset(self):
        # The old model added a flat 36 minutes to sunset. 36 is only what 8.5
        # degrees happens to equal in Jerusalem at the equinox; the gap widens
        # through the summer, and freezing it let Shabbat out early in June.
        # This is the regression that pins the difference as real.
        equinox = compute_zmanim(2026, 3, 20, 31.7683, 35.2137, 779)
        midsummer = compute_zmanim(2026, 6, 20, 31.7683, 35.2137, 779)

        equinox_gap = equinox["tset_hakohavim_shabbat"] - equinox["shkia"]
        summer_gap = midsummer["tset_hakohavim_shabbat"] - midsummer["shkia"]

        self.assertGreater(summer_gap - equinox_gap, 4.0)

    def test_shabbat_exit_and_nightfall_are_one_definition(self):
        # Two product-level names, one halachic moment. Kept as separate keys so
        # a future stricter Shabbat exit is a one-line change that saved
        # schedules follow automatically.
        values = compute_zmanim(2026, 6, 5, 31.7683, 35.2137, 779)
        self.assertEqual(values["tset_hakohavim"], values["tset_hakohavim_shabbat"])

    def test_elevation_moves_only_the_visible_sunrise_and_sunset(self):
        # The reference library corrects getSunrise/getSunset for elevation but
        # derives every other zman from sea level (useElevation defaults off).
        # Getting this backwards is what shipped Jerusalem's sunset ~5 minutes
        # early, so it is pinned rather than left to the golden table alone.
        sea = compute_zmanim(2026, 6, 5, 31.7683, 35.2137, 0)
        high = compute_zmanim(2026, 6, 5, 31.7683, 35.2137, 779)

        self.assertGreater(high["shkia"] - sea["shkia"], 4.0)
        self.assertLess(high["netz_hachama"] - sea["netz_hachama"], -4.0)

        for key in ("sof_zman_shema_gra", "sof_zman_tfilla_gra", "mincha_gedola",
                    "mincha_ketana", "plag_hamincha", "chatzot_hayom",
                    "chatzot_halayla", "candle_lighting", "tset_hakohavim",
                    "tset_hakohavim_shabbat", "tset_hakohavim_rabeinu_tam",
                    "alot_hashachar", "talit_and_tefillin"):
            with self.subTest(zman=key):
                self.assertEqual(sea[key], high[key])

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
                )
                self.assertLess(values["candle_lighting"], values["shkia"])
                self.assertLess(values["shkia"], values["tset_hakohavim_shabbat"])
                self.assertLess(values["netz_hachama"], values["chatzot_hayom"])

    def test_city_profiles_carry_geography_only(self):
        # A city is a location. Halachic offsets are product rules, not city
        # data -- they lived here once, disagreed with what was computed, and
        # nobody noticed because nothing read them.
        for city_id, city in load_cities().items():
            with self.subTest(city=city_id):
                self.assertEqual(
                    {"name_he", "lat", "lon", "elevation"}, set(city))

    def test_candle_lighting_is_the_product_offset_before_sea_level_sunset(self):
        # Pins the one country-wide candle offset. Measured at altitude 0, where
        # shkia (elevation-corrected) and the sea-level sunset candle lighting is
        # derived from are the same instant. They are NOT the same higher up:
        # in Jerusalem (779 m) shkia is minutes later than sea-level sunset, so
        # candle lighting lands ~23 min before the shkia the UI displays, not 18.
        # That is deliberate, and it is what the reference library does --
        # getCandleLighting reads sea level sunset whatever useElevation says.
        values = compute_zmanim(2026, 6, 5, 32.0853, 34.7818, 0)
        self.assertAlmostEqual(
            CANDLE_OFFSET_MINUTES,
            values["shkia"] - values["candle_lighting"],
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

    def test_israel_diaspora_parasha_divergence_5786(self):
        # שבועות ה׳תשפ״ו: יו"ט שני של גלויות חל בשבת (2026-05-23) — בישראל
        # קראו "נשא" ובחו"ל את קריאת החג, ומכאן חו"ל מפגר בפרשה אחת עד
        # שמאחדים חוקת-בלק. שני הלוחות חייבים לחיות זה לצד זה באותו מנוע.
        divergent_weeks = [
            ((2026, 5, 30), ("behaalosecha",), ("naso",)),
            ((2026, 6, 6),  ("shelach",),      ("behaalosecha",)),
            ((2026, 6, 13), ("korach",),       ("shelach",)),
            ((2026, 6, 20), ("chukas",),       ("korach",)),
            # שבת ההשלמה: בישראל בלק לבד, בחו"ל חוקת-בלק מאוחדות
            ((2026, 6, 27), ("balak",),        ("chukas", "balak")),
        ]
        for (y, m, d), israel, diaspora in divergent_weeks:
            self.assertEqual(israel, parasha(y, m, d, in_israel=True),
                             "IL {}-{}-{}".format(y, m, d))
            self.assertEqual(diaspora, parasha(y, m, d, in_israel=False),
                             "Diaspora {}-{}-{}".format(y, m, d))

        # אחרי האיחוד הלוחות מסונכרנים שוב
        for y, m, d in ((2026, 7, 4), (2026, 7, 11)):
            self.assertEqual(parasha(y, m, d, in_israel=True),
                             parasha(y, m, d, in_israel=False),
                             "resync {}-{}-{}".format(y, m, d))
        self.assertEqual(("matos", "masei"), parasha(2026, 7, 11, in_israel=True))

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

    def test_motzei_assur_bemelacha(self):
        # שבת רגילה → מוצאי תקין
        shabbat = date_info(2026, 6, 6, in_israel=True)   # שבת, יום ז׳
        self.assertTrue(shabbat["is_motzei_assur_bemelacha"])

        # יו"כ (חמישי) — אסור + לא ערב דבר → מוצאי תקין
        yk = date_info(2025, 10, 2, in_israel=True)   # י׳ תשרי ה׳תשפ״ו = יום כיפור
        self.assertTrue(yk["is_motzei_assur_bemelacha"], "יו״כ — מוצאי תקין")

        # ר"ה יום א׳ (לא שישי) → מוצאי חסום כי יום ב׳ ממשיך
        rh1 = date_info(2025, 9, 23, in_israel=True)   # א׳ תשרי ה׳תשפ״ו (יום שלישי)
        self.assertEqual(1, rh1["j_day"])
        self.assertFalse(rh1["is_motzei_assur_bemelacha"], "ר״ה יום א׳ — מוצאי חסום")

        # ר"ה יום ב׳ (יום רביעי) → מוצאי תקין
        rh2 = date_info(2025, 9, 24, in_israel=True)   # ב׳ תשרי ה׳תשפ״ו
        self.assertTrue(rh2["is_motzei_assur_bemelacha"], "ר״ה יום ב׳ — מוצאי תקין")

        # שמיני עצרת בחו"ל → מוצאי חסום (ערב שמחת תורה)
        shmini_galut = date_info(2025, 10, 14, in_israel=False)
        self.assertFalse(shmini_galut["is_motzei_assur_bemelacha"])

        # שמחת תורה בחו"ל → מוצאי תקין
        simchat_torah = date_info(2025, 10, 15, in_israel=False)
        self.assertTrue(simchat_torah["is_motzei_assur_bemelacha"])

        # יום ז׳ פסח בחו"ל (כ"א ניסן, שבת) → מוצאי חסום כי יום ח׳ ממשיך
        pesach7_galut = date_info(2025, 4, 19, in_israel=False)
        self.assertEqual(21, pesach7_galut["j_day"])
        self.assertFalse(pesach7_galut["is_motzei_assur_bemelacha"], "יום ז׳ פסח בחו״ל — מוצאי חסום")

        # יום ח׳ פסח בחו"ל (כ"ב ניסן) → מוצאי תקין
        pesach8_galut = date_info(2025, 4, 20, in_israel=False)
        self.assertTrue(pesach8_galut["is_motzei_assur_bemelacha"], "יום ח׳ פסח בחו״ל — מוצאי תקין")

    def test_calendar_caches_are_bounded(self):
        for year in range(5000, 5100):
            hebrew_cal.days_in_jewish_year(year)
            hebrew_cal.sorted_months_in_jewish_year(year)
        self.assertLessEqual(len(hebrew_cal._cache_elapsed), hebrew_cal._CACHE_LIMIT)
        self.assertLessEqual(len(hebrew_cal._cache_year_days), hebrew_cal._CACHE_LIMIT)
        self.assertLessEqual(len(hebrew_cal._cache_months), hebrew_cal._CACHE_LIMIT)


if __name__ == "__main__":
    unittest.main()
