"""The panel's boot sentinel is a contract between two files that cannot import
each other.

`main.py` prints it once the loop is up; `clean_board.py` hardware-resets the
board and greps the boot output for it, to tell "main.py is gone" from "main.py
ran again and the RGB DMA is live". That distinction is what makes the copies
that follow safe: a transfer onto a board with live DMA corrupts the VFS
(LoadProhibited). Every deploy and every hardware test run starts there.

Nothing links the two. `main.py` only ever runs on the device (it imports
`lvgl`), `clean_board.py` only on the host (it imports `serial`), so the
one-source rule cannot apply and this is the pinning test it falls back to --
same reason as tests/test_zman_keys_are_in_sync.py.

It carries more weight than most pins, because the runtime check is on the
*failure* path only: `clean_board` reads the sentinel after removing main.py, so
it is looked for exactly when the removal did NOT take. A successful deploy --
the normal case, hundreds of runs -- never exercises it. Drift the string on one
side and nothing goes red; the guard just quietly becomes a no-op, and the
symptom arrives later as a corrupt filesystem.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "products" / "panel"
MAIN = PANEL / "device" / "main.py"
CLEAN_BOARD = PANEL / "host" / "clean_board.py"


def _read(path):
    return path.read_text(encoding="utf-8")


def _named(text, pattern, path):
    found = re.search(pattern, text, re.M)
    if found is None:
        raise AssertionError(
            "{} no longer declares BOOT_SENTINEL as a module-level literal; "
            "this test reads it by name".format(path.name))
    return found.group(1)


class BootSentinelSyncTests(unittest.TestCase):
    def setUp(self):
        self.main = _read(MAIN)
        self.clean_board = _read(CLEAN_BOARD)

    def test_both_sides_spell_it_the_same(self):
        printed = _named(self.main, r'^BOOT_SENTINEL = "([^"]*)"', MAIN)
        searched = _named(self.clean_board,
                          r'^BOOT_SENTINEL = b"([^"]*)"', CLEAN_BOARD)
        self.assertEqual(printed, searched,
                         "main.py prints one string and clean_board.py looks "
                         "for another; the clean-board guard is a no-op")

    def test_the_sentinel_is_not_empty(self):
        # An empty literal would make `b"" in boot` always true on one side and
        # match nothing on the other, and both sides would still agree above.
        printed = _named(self.main, r'^BOOT_SENTINEL = "([^"]*)"', MAIN)
        self.assertTrue(printed.strip())

    def test_main_actually_prints_it(self):
        # Declared but never printed = the same silent no-op, from the producing
        # side. The check below can only ever see what boot output contains.
        self.assertRegex(self.main, r"\bprint\(BOOT_SENTINEL\b")

    def test_clean_board_actually_checks_the_boot_output(self):
        # And the consuming side has to still be reading it, against the bytes
        # captured after the reset -- not merely holding the constant.
        self.assertRegex(self.clean_board, r"\bif BOOT_SENTINEL in boot\b")

    def test_neither_side_carries_a_second_copy(self):
        # The literal may appear once, in the declaration. A second occurrence
        # is a hand-written copy that this test would not be pinning.
        printed = _named(self.main, r'^BOOT_SENTINEL = "([^"]*)"', MAIN)
        for path, text in ((MAIN, self.main), (CLEAN_BOARD, self.clean_board)):
            with self.subTest(surface=path.name):
                self.assertEqual(1, text.count('"' + printed + '"'),
                                 "the sentinel is written out more than once")


if __name__ == "__main__":
    unittest.main()
