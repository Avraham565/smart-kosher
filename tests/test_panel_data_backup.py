"""The panel's /data survives a firmware flash, or the flash does not happen.

`--erase-all` wipes the board's filesystem, and /data is the user's devices,
zones, schedules and settings. flash.py backs it up first and puts it back
after, and both halves are verified by SIZE against the board's own listing
rather than by the copy's exit code -- mpremote reports success from the host
side, and the host side is not where the file landed. Task 46 is two occasions
when main.py came back at zero bytes after a copy that said it worked.

What is tested here is the comparison, because that is the part with no board
in it. Driving it from a bench means only ever seeing the happy path: a backup
is verified on a day when nothing went wrong, and the check that was supposed
to catch the bad day has never once been shown to fire.
"""

import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "products", "panel", "host"))

from run_common import compare_listings, local_listing  # noqa: E402

BOARD = {
    "endpoints.json": 545,
    "schedules.json": 2,
    "settings.json": 115,
    "zigbee_devices.json": 589,
    "zones.json": 122,
}


class CompareListingsTests(unittest.TestCase):
    def test_an_identical_copy_has_nothing_to_report(self):
        self.assertEqual(compare_listings(BOARD, dict(BOARD)), [])

    def test_a_file_that_never_arrived_is_reported(self):
        for name in BOARD:
            with self.subTest(missing=name):
                partial = dict(BOARD)
                del partial[name]
                problems = compare_listings(BOARD, partial)
                self.assertTrue(any(name in p for p in problems), problems)

    def test_a_truncated_file_is_reported(self):
        """Zero bytes is the shape the real failure took, twice."""
        for name in BOARD:
            with self.subTest(truncated=name):
                damaged = dict(BOARD, **{name: 0})
                problems = compare_listings(BOARD, damaged)
                self.assertTrue(any(name in p for p in problems), problems)

    def test_a_short_file_is_reported_not_just_an_empty_one(self):
        """A copy cut off partway is likelier than one cut off at the start."""
        damaged = dict(BOARD, **{"journal.log": 1})
        expected = dict(BOARD, **{"journal.log": 57147})
        self.assertTrue(compare_listings(expected, damaged))

    def test_an_unexpected_file_is_reported(self):
        """The restore is meant to reproduce the backup, not resemble it."""
        problems = compare_listings(BOARD, dict(BOARD, stray=1))
        self.assertTrue(any("stray" in p for p in problems), problems)

    def test_an_empty_result_against_a_full_board_is_reported(self):
        """The whole point: everything gone must not read as everything fine."""
        problems = compare_listings(BOARD, {})
        self.assertEqual(len(problems), len(BOARD))

    def test_the_check_is_not_vacuous(self):
        """A guard that fires on every input proves nothing by firing.

        The repo has already been bitten by a meta-test that passed on every
        input including an empty one, because it restated the arithmetic it
        was meant to exercise. So: the good case must come back clean.
        """
        self.assertEqual(compare_listings({}, {}), [])
        self.assertEqual(compare_listings(BOARD, dict(BOARD)), [])


class LocalListingTests(unittest.TestCase):
    def test_it_reports_the_sizes_on_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "settings.json"), "wb") as handle:
                handle.write(b"x" * 115)
            with open(os.path.join(tmp, "empty"), "wb"):
                pass
            self.assertEqual(local_listing(tmp),
                             {"settings.json": 115, "empty": 0})

    def test_a_directory_that_is_not_there_is_empty_not_an_error(self):
        """back_up_data compares this against the board; a raise would
        become a stack trace where a refusal to flash is wanted."""
        self.assertEqual(local_listing("/no/such/place/at/all"), {})

    def test_subdirectories_are_not_counted_as_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.mkdir(os.path.join(tmp, "nested"))
            self.assertEqual(local_listing(tmp), {})


if __name__ == "__main__":
    unittest.main()
