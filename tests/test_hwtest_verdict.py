"""How the host decides whether a board suite passed.

mpremote does not carry the device's exit code back. Measured on 1.28.0:
``exec "raise SystemExit(1)"`` and ``exec "raise SystemExit(0)"`` both return 0
to the host. Every board suite scored with SystemExit therefore exited 0
whether it was green or red, and the whole of the hardware verification done
this month was, in the end, a person reading stdout.

So the verdict is read from a line the suite prints. The property that makes
that safe is the one tested hardest here: no line is a failure. A board that
crashed, hung, or was reset mid-run prints nothing, and "nothing said" must
never be read as "nothing wrong" -- that is the same false green one floor up,
where it would cover every check at once.

None of this needs the board, so none of it runs there.
"""

import io
import os
import re
import sys
import unittest

HOST = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "products", "panel", "host")
HWTEST = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "products", "panel", "hwtest")
sys.path.insert(0, HOST)

import run_common  # noqa: E402  (needs the path insert above)


class VerdictTests(unittest.TestCase):
    def test_a_suite_that_said_it_passed(self):
        self.assertEqual(0, run_common.suite_verdict(
            ["88 of 88 passed", "HWTEST_RESULT pass"]))

    def test_a_suite_that_said_it_failed(self):
        self.assertEqual(1, run_common.suite_verdict(
            ["87 of 88 passed", "FAILED: something", "HWTEST_RESULT fail 1"]))

    def test_silence_is_a_failure(self):
        # The board crashed, hung, or was reset. This is the case the whole
        # design exists for: it is indistinguishable from success to anything
        # that trusts an exit code.
        self.assertEqual(1, run_common.suite_verdict(
            ["  PASS  one", "  PASS  two"]))

    def test_no_output_at_all_is_a_failure(self):
        self.assertEqual(1, run_common.suite_verdict([]))

    def test_two_verdicts_are_a_failure(self):
        # Not pedantry: two means the output is not what the parser thinks it
        # is, and a parser that guesses which one counts is guessing.
        self.assertEqual(1, run_common.suite_verdict(
            ["HWTEST_RESULT pass", "HWTEST_RESULT fail 3"]))

    def test_a_near_miss_is_not_a_pass(self):
        for spelling in ("HWTEST_RESULT passed", "HWTEST_RESULT",
                         "HWTEST_RESULT ok", "HWTEST_RESULT PASS"):
            with self.subTest(spelling=spelling):
                self.assertEqual(1, run_common.suite_verdict([spelling]))

    def test_the_word_in_a_sentence_is_not_a_verdict(self):
        self.assertEqual(1, run_common.suite_verdict(
            ["  note  HWTEST_RESULT pass is what it will print"]))

    def test_leading_whitespace_still_counts(self):
        self.assertEqual(0, run_common.suite_verdict(["   HWTEST_RESULT pass"]))


class SpellingIsPinnedTests(unittest.TestCase):
    """The suites cannot import the constant: they are MicroPython, it is host.

    An import is blocked, so CLAUDE.md's rule leaves a pinning test. If the two
    spellings ever drift, every board run reports "the suite never reported a
    result" -- loudly, which is the right direction to fail, but this says why.
    """

    def test_both_suites_print_the_word_the_host_looks_for(self):
        for name in ("hwtest_ui.py", "hwtest.py"):
            with self.subTest(suite=name):
                source = io.open(os.path.join(HWTEST, name),
                                 encoding="utf-8").read()
                self.assertIn('"{} "'.format(run_common.SUITE_RESULT), source)

    def test_the_passing_word_is_pinned_too(self):
        # suite_verdict accepts exactly "pass"; the suites must print exactly
        # that. Checking the constant alone would miss a suite saying "ok".
        for name in ("hwtest_ui.py", "hwtest.py"):
            with self.subTest(suite=name):
                source = io.open(os.path.join(HWTEST, name),
                                 encoding="utf-8").read()
                flat = re.sub(r"\s+", " ", source)
                self.assertIn('else "pass")', flat)


if __name__ == "__main__":
    unittest.main()
