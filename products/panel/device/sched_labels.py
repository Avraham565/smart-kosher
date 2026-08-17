# Hebrew labels + option orders for the schedule wizard and descriptions. Pure
# data (no LVGL), shared by sched_describe and schedule_add.
#
# The keys below are restated rather than pulled from the domain, and that is
# deliberate twice over. This module loads on the device before the display
# exists, so it stays free of dependencies -- the documented device constraint
# CLAUDE.md names, and tests/test_zman_keys_are_in_sync.py enforces it as a
# plain substring check over this whole file (mind the wording of any comment
# you add here). And a label map has to name every key it labels, so pulling
# the vocabulary in would not remove one line of it.
#
# What could actually drift -- the key set no longer matching the domain's --
# is pinned as full equality by tests/test_schedule_vocab_is_in_sync.py, for
# both the zmanim and the recurrence types. That is the single source doing its
# job through a test rather than a dependency, which is what the rule asks for
# when the dependency is the thing that is blocked.

ZMAN_NAMES = {
    "alot_hashachar": "עלות השחר", "talit_and_tefillin": "טלית ותפילין",
    "netz_hachama": "נץ החמה", "sof_zman_shema_mga": "סוף ק״ש מג״א",
    "sof_zman_shema_gra": "סוף ק״ש גר״א", "sof_zman_tfilla_mga": "סוף תפילה מג״א",
    "sof_zman_tfilla_gra": "סוף תפילה גר״א", "chatzot_hayom": "חצות היום",
    "mincha_gedola": "מנחה גדולה", "mincha_gedola_30min": "מנחה גדולה 30׳",
    "mincha_ketana": "מנחה קטנה", "plag_hamincha": "פלג המנחה",
    "shkia": "שקיעה", "candle_lighting": "הדלקת נרות",
    "tset_hakohavim": "צאת הכוכבים", "tset_hakohavim_shabbat": "צאת שבת",
    "tset_hakohavim_rabeinu_tam": "רבינו תם", "chatzot_halayla": "חצות הלילה",
}

ZMAN_ORDER = (
    "alot_hashachar", "talit_and_tefillin", "netz_hachama",
    "sof_zman_shema_mga", "sof_zman_shema_gra",
    "sof_zman_tfilla_mga", "sof_zman_tfilla_gra",
    "chatzot_hayom", "mincha_gedola", "mincha_gedola_30min",
    "mincha_ketana", "plag_hamincha", "shkia", "candle_lighting",
    "tset_hakohavim", "tset_hakohavim_shabbat",
    "tset_hakohavim_rabeinu_tam", "chatzot_halayla",
)

RECURRENCE_NAMES = {
    "daily": "כל יום", "days_of_week": "ימים בשבוע",
    "assur_bemelacha": "שבת ויו״ט", "erev_assur_bemelacha": "ערב שבת ויו״ט",
    "motzei_assur_bemelacha": "מוצאי שבת ויו״ט", "chol_hamoed": "חול המועד",
    "rosh_chodesh": "ראש חודש", "hebrew_day_of_month": "יום בחודש עברי",
    "hebrew_date": "תאריך עברי", "gregorian_date": "תאריך לועזי",
    "one_time": "פעם אחת",
}

# Recurrence types the wizard offers now (no extra date fields to collect),
# ordered by how central they are to the product: day-of-week and the
# assur-bemelacha (Shabbat/Yom Tov) family first.
RECURRENCE_SIMPLE = (
    "days_of_week", "assur_bemelacha", "erev_assur_bemelacha",
    "motzei_assur_bemelacha", "daily", "rosh_chodesh", "chol_hamoed",
)

# (label, index) -- planner uses 0=Monday..6=Sunday ((dow-2)%7).
DAYS_OF_WEEK = (
    ("ראשון", 6), ("שני", 0), ("שלישי", 1), ("רביעי", 2),
    ("חמישי", 3), ("שישי", 4), ("שבת", 5),
)
