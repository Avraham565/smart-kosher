"""The UART protocol vocabulary, pinned across C and Markdown.

CLAUDE.md's rule: a concept living in two places with no import between them
gets one source, and where an import is impossible it gets a pinning test.
Firmware C and a Markdown document are that case about as plainly as it gets,
and the document is not decoration -- it is what the hub side is written
against, and what anyone debugging a field fault reads first. A code the
coordinator can emit and the document does not list is a code that will be met
with a search that turns up nothing.

Both directions matter and they fail differently:

  * a code in C and not in the document is an undocumented failure mode;
  * a code in the document and not in C is a promise nothing keeps, which
    sends the reader hunting for a branch that does not exist.

So these are asserted as full equality, not as containment.

Precedents: tests/test_zman_keys_are_in_sync.py (five surfaces, two of them
parsed textually) and tests/test_boot_sentinel_is_in_sync.py.
"""

import io
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "firmware" / "h2_coordinator" / "main"
ZB_C = MAIN / "zb.c"
LINK_C = MAIN / "link.c"
PROTOCOL_DOC = ROOT / "docs" / "UART_PROTOCOL.md"

# send_error(rid, "code", msg) -- the second argument. The function's own
# declaration takes `const char *code` there, so it cannot match.
_SEND_ERROR = re.compile(r'send_error\(\s*[^,()]+,\s*"([a-z_]+)"')
# send_link_error("code") -- the framing layer answers before any request id
# exists, so it has its own, narrower emitter.
_SEND_LINK_ERROR = re.compile(r'send_link_error\(\s*"([a-z_]+)"\s*\)')
_LOWER_LITERAL = re.compile(r'"([a-z_]+)"')


def _read(path):
    return io.open(str(path), encoding="utf-8").read()


def _reporting_reasons(source):
    """Every ``reason`` handed to report_reporting_outcome.

    Taken per call rather than by argument position: the calls wrap across
    lines and the reason sits fifth, so counting commas would be the fragile
    way to do it. Each call is read up to its terminating semicolon, which is
    also what keeps the declaration and the definition out -- neither carries
    a lowercase string literal before its first one.
    """
    reasons = set()
    for chunk in source.split("report_reporting_outcome(")[1:]:
        call = chunk.split(";", 1)[0]
        reasons.update(_LOWER_LITERAL.findall(call))
    return reasons


def _documented(marker, source):
    """The backticked tokens introduced by ``marker``, to the end of its line.

    The error-code list wraps over three lines and ends in a full stop; the
    reasons list is inside a table cell and ends at the cell divider. Reading
    to the end of the paragraph covers both without one regex per shape.
    """
    index = source.index(marker)
    tail = source[index + len(marker):]
    end = tail.index("\n\n") if "\n\n" in tail else len(tail)
    paragraph = tail[:end].split("|")[0]
    return set(re.findall(r"`([a-z_]+)`", paragraph))


class ErrorCodeSyncTests(unittest.TestCase):
    def setUp(self):
        self.emitted = set(_SEND_ERROR.findall(_read(ZB_C)))
        self.emitted |= set(_SEND_LINK_ERROR.findall(_read(LINK_C)))
        self.documented = _documented("Error codes:", _read(PROTOCOL_DOC))

    def test_the_parser_found_something_to_compare(self):
        # A regex that silently stops matching would make every assertion
        # below pass against an empty set. The counts do not need to be exact,
        # only obviously alive.
        self.assertGreater(len(self.emitted), 10)
        self.assertGreater(len(self.documented), 10)

    def test_every_code_the_coordinator_emits_is_documented(self):
        self.assertEqual(
            set(), self.emitted - self.documented,
            "the coordinator can send these and UART_PROTOCOL.md does not "
            "list them")

    def test_every_documented_code_exists_in_the_firmware(self):
        self.assertEqual(
            set(), self.documented - self.emitted,
            "UART_PROTOCOL.md promises these and no firmware branch sends "
            "them")

    def test_missing_ieee_and_bad_ieee_are_both_present_and_distinct(self):
        # A missing field and a malformed one are different faults with
        # different fixes, and they sit two lines apart in zb.c. Collapsing
        # them into one code would make this file green and the protocol
        # poorer, so the distinction is pinned rather than left to judgement.
        self.assertIn("missing_ieee", self.emitted)
        self.assertIn("bad_ieee", self.emitted)
        self.assertIn("missing_ieee", self.documented)
        self.assertIn("bad_ieee", self.documented)


class ReportingReasonSyncTests(unittest.TestCase):
    def setUp(self):
        self.emitted = _reporting_reasons(_read(ZB_C))
        self.documented = _documented("Reasons:", _read(PROTOCOL_DOC))

    def test_the_parser_found_something_to_compare(self):
        self.assertGreater(len(self.emitted), 4)
        self.assertGreater(len(self.documented), 4)

    def test_every_reason_the_coordinator_emits_is_documented(self):
        self.assertEqual(
            set(), self.emitted - self.documented,
            "reporting_failed can carry these reasons and the document does "
            "not list them")

    def test_every_documented_reason_exists_in_the_firmware(self):
        self.assertEqual(
            set(), self.documented - self.emitted,
            "the document lists reasons no firmware branch produces")


if __name__ == "__main__":
    unittest.main()
