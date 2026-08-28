"""The touch controller's registers are compared against a baseline.

Task 59. Four numbers -- press level, leave level, de-jitter counts, report
period -- decide whether a tap is felt and how long it takes. They live in the
GT911's own flash, not in this repository: they survive power-off, a reflash
and even ``--erase-all``. Nothing in the tree could see them, so the only
protection against a silent change was that someone remembered the old values.

``run_hwtest_ui.py --probe-touch`` now writes what the controller reports into
``products/panel/host/touch_registers.json`` on every run. That turns the four
numbers into a record rather than a recollection, and this file is what makes
the record load-bearing: it compares the half the board wrote against the half
a person wrote.

The two halves have to stay independent for that to mean anything. The probe
only ever rewrites ``observed``; ``expected`` is edited by hand. If the probe
maintained both, this test would compare a file against itself and pass on
every input, which is the false green CLAUDE.md devotes a section to.

Red here is not a bug in the test. It means the board on the bench is not in
the state the panel was tuned to -- decide which side is wrong before editing
either one.
"""

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORD = ROOT / "products" / "panel" / "host" / "touch_registers.json"

REGISTERS = ("press_level", "leave_level", "shake_count", "refresh_rate")


def _load():
    with RECORD.open(encoding="utf-8") as handle:
        return json.load(handle)


class TouchRegisterBaseline(unittest.TestCase):

    def test_the_record_exists_and_carries_both_halves(self):
        self.assertTrue(RECORD.exists(), "{} is missing".format(RECORD))
        record = _load()
        for half in ("expected", "observed", "previous"):
            self.assertIn(half, record,
                          "{} has no {!r} section".format(RECORD.name, half))

    def test_every_register_is_present_in_every_half(self):
        # Without this, a half that lost a key would compare None to None and
        # agree. The comparison below is only worth reading if both sides are
        # complete.
        record = _load()
        for half in ("expected", "observed", "previous"):
            for name in REGISTERS:
                self.assertIn(name, record[half],
                              "{} is missing from {!r}".format(name, half))
                self.assertIsInstance(record[half][name], int)

    def test_the_controller_matches_the_baseline(self):
        record = _load()
        expected, observed = record["expected"], record["observed"]
        drift = {name: (observed[name], expected[name])
                 for name in REGISTERS if observed[name] != expected[name]}
        self.assertEqual(
            drift, {},
            "the controller has drifted from the tuned baseline: " + ", ".join(
                "{} is {} not {}".format(name, got, want)
                for name, (got, want) in sorted(drift.items())))

    def test_leave_level_stays_below_press_level(self):
        # The invariant probe_touch refuses to write past: at or above the
        # press level the controller chatters between pressed and released in
        # the middle of a steady touch. Anchored for both halves, because a
        # hand edit to expected is exactly as able to break it as a board is.
        record = _load()
        for half in ("expected", "observed", "previous"):
            self.assertLess(record[half]["leave_level"],
                            record[half]["press_level"],
                            "{}: leave_level must stay below press_level"
                            .format(half))

    def test_the_way_back_is_a_different_point(self):
        # previous is the return path if a retune makes the panel worse. Equal
        # to expected, it is not a return path at all -- it is a copy that
        # would quietly agree with anything.
        record = _load()
        self.assertNotEqual(
            [record["previous"][n] for n in REGISTERS],
            [record["expected"][n] for n in REGISTERS],
            "previous and expected are the same values, so there is nothing "
            "to go back to")

    def test_the_observed_half_says_when_and_where_it_was_read(self):
        # A reading with no timestamp cannot be told from a value typed in to
        # make this file green, which is the one failure mode that would make
        # the whole record worthless.
        observed = _load()["observed"]
        for field in ("read_at", "port"):
            self.assertIn(field, observed)
            self.assertTrue(str(observed[field]).strip())


if __name__ == "__main__":
    unittest.main()
