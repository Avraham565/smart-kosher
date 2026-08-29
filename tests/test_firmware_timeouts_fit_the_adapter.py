"""A coordinator transaction must expire before its caller stops waiting.

The rule is written in ``zb.c`` itself, above ``CMD_TIMEOUT_MS``::

    A command is expected to be confirmed well inside this; the S3 waits
    1500ms for an ack, so the coordinator must answer *before* that -- an
    expiry that fires after the caller gave up is useless.

Nothing enforced it, and ``cmd_remove_device`` broke it: it allocated its
transaction with ``REPORTING_TIMEOUT_MS`` (8000ms), the constant whose comment
says it is for a "background chain nobody blocks on". The adapter waited
1500ms, popped the pending slot, and returned "timeout" -- and the real verdict
arrived 6.5 seconds later with nowhere to land and was dropped in silence.
That is exactly the fault 63b1465 was written to remove, returning through two
numbers that disagree rather than through any code. Measured on the board:
``leave verdict timeout after 1511ms (firmware expiry is 8000ms)``.

Two files, two languages, no import between them: CLAUDE.md's case for a
pinning test, the same shape as ``test_protocol_vocab_is_in_sync.py``.

The firmware says which transactions have a caller, and it says it
structurally rather than in prose. ``zb_txn_alloc`` takes the request id, and
the background chains -- bind, configure_reporting -- pass ``NULL`` because no
one is waiting for them. So "carries a rid" is the test's definition of "has a
caller", read out of the source instead of listed here by hand.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ZB_C = ROOT / "firmware" / "h2_coordinator" / "main" / "zb.c"

# Below this many, the parse found something other than the firmware and the
# comparison would pass over an empty set. Six allocations exist today; the
# floor is deliberately under that so adding one is not a failure, and far
# enough above zero that a regex that stopped matching is.
_MIN_ALLOCATIONS = 5
_MIN_DEFINES = 3

_DEFINE = re.compile(r"#define\s+(\w*TIMEOUT_MS)\s+(\d+)")
_ALLOC = re.compile(
    r"zb_txn_alloc\(\s*(TXN_KIND_\w+)\s*,\s*(\w+)\s*,(.*?)\)", re.DOTALL)


def _timeouts():
    return {name: int(value)
            for name, value in _DEFINE.findall(ZB_C.read_text(encoding="utf-8"))}


def _allocations():
    """``(kind, rid_argument, timeout_constant)`` for every transaction."""
    out = []
    for kind, rid, rest in _ALLOC.findall(ZB_C.read_text(encoding="utf-8")):
        names = re.findall(r"\b(\w+)\b", rest)
        out.append((kind, rid, names[-1] if names else None))
    return out


def _adapter_budget_ms():
    """What the Python side is prepared to wait, per transaction kind."""
    from smart_kosher.adapters.zigbee_gateway import (
        _DEFAULT_ACK_TIMEOUT_MS,
        _LEAVE_VERDICT_TIMEOUT_MS,
    )
    return {"TXN_KIND_REMOVE": _LEAVE_VERDICT_TIMEOUT_MS}, _DEFAULT_ACK_TIMEOUT_MS


class FirmwareTimeoutsFitTheAdapter(unittest.TestCase):

    def test_the_firmware_can_be_read_at_all(self):
        # The guard the rest of the file leans on. A regex that stops matching
        # -- a rename, a reformat, a moved file -- would otherwise turn every
        # check below into a loop over nothing, and this file would report that
        # every timeout agrees while reading none of them.
        self.assertTrue(ZB_C.exists(), "{} is missing".format(ZB_C))
        self.assertGreaterEqual(len(_allocations()), _MIN_ALLOCATIONS)
        self.assertGreaterEqual(len(_timeouts()), _MIN_DEFINES)

    def test_every_timeout_named_by_an_allocation_is_defined(self):
        defined = _timeouts()
        for kind, _rid, constant in _allocations():
            self.assertIn(constant, defined,
                          "{} allocates with {}, which is not a "
                          "#define'd timeout".format(kind, constant))

    def test_a_transaction_with_a_caller_expires_before_the_caller_does(self):
        defined = _timeouts()
        per_kind, default = _adapter_budget_ms()
        answered = [a for a in _allocations() if a[1] != "NULL"]
        # Without this, a firmware that stopped passing rids anywhere would
        # empty the loop and pass.
        self.assertTrue(answered, "no transaction carries a request id")

        for kind, _rid, constant in answered:
            firmware = defined[constant]
            budget = per_kind.get(kind, default)
            self.assertLess(
                firmware, budget,
                "{} answers a caller but expires after {}ms, while the adapter "
                "waits {}ms. The verdict arrives {}ms after _command has "
                "popped the pending slot, so it lands nowhere and is "
                "dropped.".format(kind, firmware, budget, firmware - budget))

    def test_the_background_chains_are_allowed_to_take_their_time(self):
        # The other half of the rule, and the reason it is not simply "every
        # timeout must be under 1500". bind and configure_reporting really do
        # need seconds, and they get them by having no caller -- which is what
        # makes 8000ms correct there and wrong for a leave.
        defined = _timeouts()
        _per_kind, default = _adapter_budget_ms()
        background = [a for a in _allocations() if a[1] == "NULL"]
        self.assertTrue(background, "no transaction runs unwaited")
        self.assertTrue(
            any(defined[c] > default for _k, _r, c in background),
            "every background chain now fits inside the ack budget, so this "
            "file no longer distinguishes the two cases it exists to separate")


if __name__ == "__main__":
    unittest.main()
