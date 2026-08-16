"""The recurrence and action lists cross the same three surfaces the zman
keys do, and nothing linked them.

`tests/test_zman_keys_are_in_sync.py` exists because retiring one zman key
meant editing seven files. Recurrence types have the identical shape: the
domain decides what a schedule may recur on, and two UI surfaces each carry
their own Hebrew labels. Nothing links them at runtime.

The failure is silent in both directions. The desktop form builds its options
by iterating RECURRENCE_LABELS (views/schedules.js), so a type added to the
domain and forgotten here simply never appears -- a capability that exists in
the core and cannot be reached. A type removed from the domain but left here
is worse: the form still offers it, and the request fails validation at submit.

Parsed as text rather than imported, for the same reasons the zman test gives:
`labels.js` is JavaScript, and `sched_labels.py` is loaded on the device
before the display exists, so it must stay import-free.
"""

import re
import unittest
from pathlib import Path

from smart_kosher.domain.actions import ACTION_TYPES
from smart_kosher.domain.schedules import RECURRENCE_TYPES

ROOT = Path(__file__).resolve().parents[1]
SCHED_LABELS = ROOT / "products" / "panel" / "device" / "sched_labels.py"
SCHEDULE_ADD = ROOT / "products" / "panel" / "device" / "schedule_add.py"
CLIENT_LABELS = ROOT / "apps" / "desktop" / "ui" / "js" / "labels.js"


def _read(path):
    return path.read_text(encoding="utf-8")


def _py_dict_keys(text, name):
    block = text.split(name + " = {")[1].split("}")[0]
    return set(re.findall(r'"([a-z_0-9]+)":', block))


def _py_tuple_values(text, name):
    block = text.split(name + " = (")[1].split(")")[0]
    return set(re.findall(r'"([a-z_0-9]+)"', block))


def _js_object_keys(text, name):
    block = text.split(name + " = {")[1].split("}")[0]
    return set(re.findall(r"([a-z_0-9]+):", block))


class RecurrenceSyncTests(unittest.TestCase):
    def setUp(self):
        self.domain = set(RECURRENCE_TYPES)
        self.assertEqual(11, len(self.domain), "the recurrence list changed size")

    def test_panel_labels_cover_exactly_the_domain(self):
        names = _py_dict_keys(_read(SCHED_LABELS), "RECURRENCE_NAMES")
        self.assertEqual(self.domain, names)

    def test_client_labels_cover_exactly_the_domain(self):
        labels = _js_object_keys(_read(CLIENT_LABELS), "RECURRENCE_LABELS")
        self.assertEqual(self.domain, labels)

    def test_panel_wizard_offers_a_subset_and_invents_nothing(self):
        # RECURRENCE_SIMPLE is deliberately narrower than the domain -- the
        # wizard only offers types that need no extra date field. Containment
        # is the invariant; coverage is not.
        simple = _py_tuple_values(_read(SCHED_LABELS), "RECURRENCE_SIMPLE")
        self.assertEqual(set(), simple - self.domain)
        self.assertTrue(simple)

    def test_every_offered_recurrence_has_a_label(self):
        text = _read(SCHED_LABELS)
        simple = _py_tuple_values(text, "RECURRENCE_SIMPLE")
        names = _py_dict_keys(text, "RECURRENCE_NAMES")
        self.assertEqual(set(), simple - names)


class ActionSyncTests(unittest.TestCase):
    def setUp(self):
        self.domain = set(ACTION_TYPES)

    def test_client_action_labels_invent_nothing(self):
        # Containment, not equality: `toggle` is a manual-control action and
        # is banned in schedules (domain/schedules.py), so the schedule label
        # map is right not to carry it.
        labels = _js_object_keys(_read(CLIENT_LABELS), "ACTION_LABELS")
        self.assertEqual(set(), labels - self.domain)

    def test_panel_wizard_actions_are_domain_values_without_toggle(self):
        # The wizard writes its two options as literals; pin them to the
        # domain so a renamed action cannot leave a button that stores a
        # value validate_action rejects.
        # Split on a top-level "\ndef " -- _action() nests a `def pick`, and
        # splitting on bare "def " cuts the block before the options.
        block = _read(SCHEDULE_ADD).split("def _action():")[1].split("\ndef ")[0]
        offered = set(re.findall(r'\("[^"]+",\s*"([a-z_]+)"\)', block))
        self.assertEqual({"on", "off"}, offered)
        self.assertEqual(set(), offered - self.domain)
        self.assertNotIn("toggle", offered)


if __name__ == "__main__":
    unittest.main()
