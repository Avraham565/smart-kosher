# End-to-end zmanim check -- runs ON the panel and prints what the device
# actually computes, so the host can diff it against the committed reference
# table. No display, no /data writes.
#
# This is the only check that covers the device's arithmetic. The panel's
# MicroPython is a single-precision float build: near a Julian day's 2.46e6,
# floats are spaced 0.25 apart, so an offset added to one silently vanishes.
# CPython cannot see that, and the host suite passes either way -- which is
# exactly how the two-pass NOAA refinement was dead on hardware for months
# while every test was green. Agreement here is worth more than agreement there.
#
# Usage (from the host):  python products/panel/host/run_hwtest_zmanim.py

from smart_kosher.data import load_cities
from smart_kosher.zmanim import compute_zmanim

KEYS = ("alot_hashachar", "talit_and_tefillin", "netz_hachama",
        "sof_zman_shema_gra", "sof_zman_shema_mga",
        "sof_zman_tfilla_gra", "sof_zman_tfilla_mga",
        "chatzot_hayom", "mincha_gedola", "mincha_gedola_30min",
        "mincha_ketana", "plag_hamincha", "shkia",
        "tset_hakohavim", "tset_hakohavim_shabbat",
        "tset_hakohavim_rabeinu_tam", "chatzot_halayla", "candle_lighting")

# Spread deliberately: the extremes of latitude and elevation, both solstices,
# both equinoxes, and a leap day.
CITIES = ("jerusalem", "tel_aviv", "eilat", "zfat", "tiberias", "mitzpe_ramon")
DATES = ((2024, 2, 29), (2025, 3, 20), (2026, 6, 21),
         (2026, 9, 22), (2027, 12, 21))


def run():
    cities = load_cities()
    print("BEGIN")
    for city_id in CITIES:
        city = cities[city_id]
        for year, month, day in DATES:
            z = compute_zmanim(year, month, day,
                               city["lat"], city["lon"], city["elevation"])
            values = ",".join("%.1f" % (z[k] * 60.0) for k in KEYS)
            print("%s|%04d-%02d-%02d|%s" % (city_id, year, month, day, values))
    print("END")
