"""The desktop client's per-gang state: its JS tests, and the rule they share.

The panel and the desktop client read the same /api/zigbee/devices payload and
had the same bug -- on_off taken from the device record, so both gangs of a
two-gang switch showed one state. The panel's half is fixed and covered by
tests/test_panel_state_layer.py. This is the other half.

The logic is pure on both sides, so neither needs hardware. What this file adds
is that the JavaScript half runs inside the normal `pytest -q` rather than
beside it, because a suite nobody runs is a suite that does not exist.
"""

import io
import os
import re
import shutil
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS = os.path.join(ROOT, "apps", "desktop", "ui", "js")
STORE = os.path.join(JS, "store.js")
PANEL = os.path.join(ROOT, "products", "panel", "device", "dev_common.py")


def read(path):
    return io.open(path, encoding="utf-8").read()


class NodeSuiteTests(unittest.TestCase):
    def test_the_javascript_tests_pass(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is not installed; the JS half cannot run here")
        result = subprocess.run(
            [node, "--test", os.path.join(JS, "gang_state.test.mjs")],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", cwd=ROOT)
        self.assertEqual(0, result.returncode,
                         "node --test failed:\n" + (result.stdout or "")
                         + (result.stderr or ""))


class TheRuleIsTheSameOnBothSidesTests(unittest.TestCase):
    """Python one side, JavaScript the other: the import is blocked.

    CLAUDE.md's rule for a concept crossing a boundary an import cannot cross
    is a pinning test, and this is one. The two implementations answer the same
    question about the same payload, and the way they would drift is silently:
    one of them starts calling "unknown" something the other calls "off", and
    the two screens disagree about a switch with nothing failing anywhere.
    """

    def test_the_four_tokens_are_spelled_the_same(self):
        panel = read(PANEL)
        store = read(STORE)
        for name, value in (("STATE_ON", "on"), ("STATE_OFF", "off"),
                            ("STATE_UNKNOWN", "unknown"),
                            ("STATE_UNREACHABLE", "unreachable")):
            with self.subTest(token=name):
                self.assertIn('{} = "{}"'.format(name, value), panel)
                self.assertIn("{} = '{}'".format(name, value), store)

    def test_both_sides_ask_about_the_same_cluster(self):
        # 6 is OnOff. It decides which endpoints count as gangs, and therefore
        # when a missing cell must refuse to borrow the neighbour's value.
        self.assertIn("6 in (clusters.get(str(ep)) or [])", read(PANEL))
        self.assertIn("const CLUSTER_ON_OFF = 6;", read(STORE))

    def test_neither_side_can_fall_back_across_gangs(self):
        # The refusal is the fix. Both express it as "more than one OnOff
        # endpoint means no device-level answer".
        self.assertIn("if len(onoff) > 1:", read(PANEL))
        self.assertIn("if (onoff.length > 1) return null;", read(STORE))

    def test_the_client_has_no_way_left_to_ask_the_device(self):
        # radioOf(endpoint) took the entity, ignored its zigbee_endpoint and
        # returned the whole device record; nine callers then read on_off off
        # it. It is gone rather than documented, so the shape that caused this
        # cannot be reached by habit.
        flat = re.sub(r"\s+", " ", read(STORE))
        self.assertNotIn("export function radioOf", flat)
        for name in ("devices.js", "device.js"):
            with self.subTest(view=name):
                source = read(os.path.join(JS, "views", name))
                self.assertNotIn("radio.on_off", source)


if __name__ == "__main__":
    unittest.main()
