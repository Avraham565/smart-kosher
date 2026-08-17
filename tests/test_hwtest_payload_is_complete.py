"""Every module a hardware suite loads is uploaded before it runs.

This pins the verification mechanism itself, which is why it matters more than
its size suggests. ``run_hwtest_ui.py`` copies a hand-written list of device
modules to the board before running the suite. A name missing from that list
does not error: the module is already on the board from an earlier deploy, so
the run quietly exercises the *old* copy and reports green.

That has now happened twice. ``clock.py`` was missing because ``shell.py``
imports it and no test named it directly. ``zone_picker.py`` was missing while
a test written specifically to drive it was added -- so the test that proved a
use-after-free fix would have been proving it against the unfixed file.

A false green in the thing that checks for bugs is worse than any bug it
catches, so the list is no longer maintained by eye. The closure is computed
from the source with ``ast``, the same mechanical approach as
``test_route_table.py`` and ``test_zman_keys_are_in_sync.py``.

The closure is deliberately strict: every import anywhere in a reachable
module counts, including the ones inside functions. Some of those only fire
when a user taps something the suite never taps, so a few modules are uploaded
that this run will not execute. That costs four file copies over USB and buys
a rule with no judgement in it -- and judgement is precisely what failed here
twice. A test that starts tapping is covered before it is written.
"""

import ast
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEVICE = os.path.join(ROOT, "products", "panel", "device")
HWTEST = os.path.join(ROOT, "products", "panel", "hwtest")
HOST = os.path.join(ROOT, "products", "panel", "host")


def _read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _device_modules():
    """Module names importable on the board from products/panel/device."""
    return set(name[:-3] for name in os.listdir(DEVICE)
               if name.endswith(".py") and name != "__init__.py")


def _imports_in(path, known):
    """Device modules imported by ``path``, from anywhere in the file.

    ast.walk rather than tree.body on purpose: the panel imports inside
    functions to break cycles (shell -> ui_home) and to keep boot cheap, and
    the miss this test exists for was exactly such an import.
    """
    found = set()
    for node in ast.walk(ast.parse(_read(path))):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            # Relative imports cannot reach the board's flat root.
            names = [node.module] if node.level == 0 and node.module else []
        else:
            continue
        for name in names:
            root = name.split(".")[0]
            if root in known:
                found.add(root)
    return found


def _closure(suite_path):
    """Every device module reachable from a suite file, transitively."""
    known = _device_modules()
    seen = set()
    queue = sorted(_imports_in(suite_path, known))
    while queue:
        name = queue.pop()
        if name in seen:
            continue
        seen.add(name)
        queue.extend(_imports_in(os.path.join(DEVICE, name + ".py"), known))
    return set(name + ".py" for name in seen)


# The two checks below are the mechanism. They are functions rather than test
# bodies so the meta-test can run *them* against a deliberately broken payload
# instead of restating their arithmetic -- a guard that restates the thing it
# guards proves only that set subtraction works.

def missing_from_payload(suite_path, payload):
    """Modules the suite loads that this payload would not refresh.

    Each one is a module the run would exercise from whatever copy the board
    happens to be carrying.
    """
    return sorted(_closure(suite_path) - set(payload))


def surplus_in_payload(suite_path, payload):
    """Names uploaded that the suite never loads."""
    return sorted(set(payload) - _closure(suite_path))


def _runners():
    """(runner, suite_path, payload) for every host runner that uploads one.

    Discovered rather than listed, so a fourth suite is covered the day it is
    written instead of the day someone remembers this file.
    """
    out = []
    for name in sorted(os.listdir(HOST)):
        if not name.startswith("run_") or not name.endswith(".py"):
            continue
        path = os.path.join(HOST, name)
        found = {}
        for node in ast.parse(_read(path)).body:
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in ("SUITE",
                                                                  "PAYLOAD"):
                    found[target.id] = ast.literal_eval(node.value)
        if "PAYLOAD" in found and "SUITE" in found:
            out.append((name, os.path.join(HWTEST, found["SUITE"]),
                        set(found["PAYLOAD"])))
    return out


class PayloadTests(unittest.TestCase):
    def setUp(self):
        self.runners = _runners()
        # If this ever empties, the test would pass by testing nothing.
        self.assertTrue(self.runners, "no host runner declares a PAYLOAD")

    def test_every_module_the_suite_loads_is_uploaded(self):
        for runner, suite, payload in self.runners:
            with self.subTest(runner=runner):
                missing = missing_from_payload(suite, payload)
                self.assertEqual(
                    missing, [],
                    "{} would run these from whatever stale copy the board "
                    "already has: {}".format(runner, ", ".join(missing)))

    def test_the_payload_carries_nothing_the_suite_never_loads(self):
        # Not cosmetic: dead weight in the list is how a reader stops trusting
        # it, and an untrusted list is one nobody updates.
        for runner, suite, payload in self.runners:
            with self.subTest(runner=runner):
                extra = surplus_in_payload(suite, payload)
                self.assertEqual(
                    extra, [],
                    "{} uploads modules its suite never imports: {}".format(
                        runner, ", ".join(extra)))

    def test_every_uploaded_name_exists(self):
        for runner, _, payload in self.runners:
            with self.subTest(runner=runner):
                for name in sorted(payload):
                    self.assertTrue(
                        os.path.exists(os.path.join(DEVICE, name)),
                        "{} uploads {}, which is not in device/".format(
                            runner, name))

    def test_the_check_reports_a_name_dropped_from_the_payload(self):
        """The guard must fail when it should. That is the entire point.

        An earlier version of this test compared ``closure`` against
        ``payload - {dropped}`` itself, and could not fail: ``dropped`` is
        taken from ``closure`` and removed from ``payload``, so the difference
        always contained it. It restated the check's arithmetic instead of
        running the check, and so proved that set subtraction works -- the very
        false-green shape this file exists to prevent, one floor up.

        This drives missing_from_payload, the function the real check calls.
        A closure that stopped following imports inside functions, or one that
        came back empty, fails here.
        """
        for runner, suite, payload in self.runners:
            with self.subTest(runner=runner):
                self.assertEqual(missing_from_payload(suite, payload), [],
                                 "baseline is not clean, nothing below means "
                                 "anything")
                for dropped in sorted(payload):
                    reported = missing_from_payload(suite,
                                                    payload - {dropped})
                    self.assertIn(
                        dropped, reported,
                        "dropping {} from {} went unnoticed".format(
                            dropped, runner))

    def test_the_closure_follows_imports_inside_functions(self):
        """Both real misses came in through a function-level import.

        clock.py was reached from shell.py's module scope, but zone_picker.py
        is imported inside the test function that drives it -- a closure built
        from tree.body alone would have missed it exactly as the hand-written
        list did. Named concretely because it is the regression, not an
        example of one; if the suite stops driving zone_picker, replace this
        with whatever it drives instead.
        """
        suite = os.path.join(HWTEST, "hwtest_ui.py")
        self.assertIn("zone_picker.py", _closure(suite))


if __name__ == "__main__":
    unittest.main()
