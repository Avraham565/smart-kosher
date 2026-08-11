"""The zman key list exists in five places. They must not drift apart.

`compute_zmanim` decides what a day contains; the domain decides what a
schedule may fire on; and three UI surfaces each carry their own Hebrew labels
and display order. Nothing links them at runtime, so a zman added or retired in
one place and forgotten in another fails quietly -- a schedule that cannot be
created, or a row on the panel with a name and no time.

That is not hypothetical: retiring `tset_hakohavim_tsom` meant editing seven
files, and the only thing that would have caught a miss was reading them all
again. This does the reading.

The two UI files are parsed as text rather than imported: `sched_labels.py`
targets MicroPython (importable here only because it is pure data, which this
test also pins), and `labels.js` is JavaScript.
"""

import re
import unittest
from pathlib import Path

from smart_kosher.domain.schedules import RETIRED_ZMAN_KEYS, ZMAN_KEYS
from smart_kosher.zmanim import compute_zmanim

ROOT = Path(__file__).resolve().parents[1]
SCHED_LABELS = ROOT / "panel_mp" / "sched_labels.py"
ZMANIM_PAGE = ROOT / "panel_mp" / "zmanim_page.py"
CLIENT_LABELS = ROOT / "client" / "ui" / "js" / "labels.js"


def _computed_keys():
    return set(compute_zmanim(2026, 8, 11, 31.7683, 35.2137, 779))


def _read(path):
    return path.read_text(encoding="utf-8")


class ZmanKeySyncTests(unittest.TestCase):
    def setUp(self):
        self.computed = _computed_keys()
        self.assertEqual(18, len(self.computed), "the day changed size")

    def test_domain_allows_exactly_what_is_computed(self):
        # A schedule may only fire on a zman that exists, and every zman that
        # exists should be schedulable.
        self.assertEqual(self.computed, set(ZMAN_KEYS))

    def test_panel_schedule_labels_cover_every_zman(self):
        text = _read(SCHED_LABELS)
        names = set(re.findall(r'"([a-z_0-9]+)":\s*"', text.split("ZMAN_ORDER")[0]))
        self.assertEqual(self.computed, names)

    def test_panel_schedule_order_covers_every_zman(self):
        text = _read(SCHED_LABELS)
        block = text.split("ZMAN_ORDER = (")[1].split(")")[0]
        self.assertEqual(self.computed, set(re.findall(r'"([a-z_0-9]+)"', block)))

    def test_panel_zmanim_page_shows_every_zman(self):
        rows = set(re.findall(r'\("([a-z_0-9]+)",\s*"', _read(ZMANIM_PAGE)))
        self.assertEqual(self.computed, rows)

    def test_client_labels_cover_every_zman(self):
        # labels.js also names non-zman things, so this is containment.
        labels = set(re.findall(r"^\s{2}([a-z_0-9]+):\s*'", _read(CLIENT_LABELS),
                                re.M))
        self.assertEqual(set(), self.computed - labels)

    def test_retired_zmanim_are_gone_from_every_surface(self):
        surfaces = {
            "compute_zmanim": self.computed,
            "ZMAN_KEYS": set(ZMAN_KEYS),
            "sched_labels.py": set(re.findall(r"[a-z_0-9]+", _read(SCHED_LABELS))),
            "zmanim_page.py": set(re.findall(r"[a-z_0-9]+", _read(ZMANIM_PAGE))),
            "labels.js": set(re.findall(r"[a-z_0-9]+", _read(CLIENT_LABELS))),
        }
        for name, keys in surfaces.items():
            with self.subTest(surface=name):
                self.assertEqual(set(), RETIRED_ZMAN_KEYS & keys)

    def test_sched_labels_stays_free_of_lvgl(self):
        # It is shared with CPython tooling and imported on the device before
        # the display exists; an import here would break both.
        self.assertNotIn("import", _read(SCHED_LABELS))


if __name__ == "__main__":
    unittest.main()
