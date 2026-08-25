"""The panel's reactive core, its store, and the per-gang state helper.

None of these had a single test. `grep -rl "reactive\\|dev_common\\|Signal"
tests/` returned nothing, while reactive.py's own header claims "Pure Python,
no LVGL -- unit-tested on CPython" and store.py says "testable on CPython".
Both were aspirations.

That gap is why the two-gang display bug survived: dev_common read and wrote
on_off at device level long after the gateway had moved to (ieee, endpoint),
and the only thing that could have caught it was a suite that did not exist.
It was found by a person looking at a screen.

dev_common is testable here now because task 35 took the LVGL out of it: it
returns a state *token* and takes its notifier as an argument, so it imports
bridge and store and nothing else. Turning a token into text and a colour is
widgets.state_look, which does need LVGL and is checked on the board.

The six per-gang checks below were moved here from hwtest_ui rather than
copied. They never touched LVGL -- they seed dicts and read a return value --
and two suites asserting the same thing drift apart. What stayed on the board
is the one check that genuinely needs it: building the add-device screen and
measuring whether anything left the glass.

MicroPython safety is not lost in the move: tests/test_core_is_micropython_safe.py
already scans products/panel/device/, so f-strings, annotations, multiple
inheritance and forbidden imports are still caught there.
"""

import os
import sys
import unittest

sys.path.insert(
    0,
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "products", "panel", "device"),
)

import dev_common  # noqa: E402  (needs the path insert above)
import reactive  # noqa: E402
import store  # noqa: E402

IEEE = "70:d0:7e:ff:fe:6e:c6:40"
ACTUATOR = "78:1c:9d:ff:fe:12:76:fa"

TWO_GANG = {"endpoints": [1, 2], "clusters": {"1": [0, 3, 6], "2": [0, 3, 6]}}


def gang(endpoint, ieee=IEEE):
    return {"id": "e{}".format(endpoint), "ieee_address": ieee,
            "zigbee_endpoint": endpoint}


class SignalTests(unittest.TestCase):
    def test_setting_an_equal_value_notifies_nobody(self):
        # This is what stops the three-second device poll repainting every
        # bound widget on the panel each time it runs.
        signal = reactive.Signal(1)
        seen = []
        reactive.effect(lambda: seen.append(signal.get()))
        self.assertEqual([1], seen)

        signal.set(1)
        self.assertEqual([1], seen, "an equal set woke the observers")

        signal.set(2)
        self.assertEqual([1, 2], seen)

    def test_an_effect_depends_only_on_what_it_read(self):
        read = reactive.Signal("a")
        ignored = reactive.Signal("x")
        runs = []
        reactive.effect(lambda: runs.append(read.get()))

        ignored.set("y")
        self.assertEqual(1, len(runs), "an unread signal woke the effect")

        read.set("b")
        self.assertEqual(2, len(runs))

    def test_peek_reads_without_subscribing(self):
        signal = reactive.Signal(1)
        runs = []

        def body():
            runs.append(signal.peek())

        reactive.effect(body)
        signal.set(2)
        self.assertEqual(1, len(runs))

    def test_a_failing_effect_does_not_freeze_the_others(self):
        # One bad binding must not propagate up through Signal.set and stop
        # every other observer -- the clock included. reactive.py promises this
        # and nothing checked it.
        signal = reactive.Signal(0)
        survivors = []

        def broken():
            signal.get()
            raise ValueError("bad binding")

        reactive.effect(broken)
        reactive.effect(lambda: survivors.append(signal.get()))

        signal.set(1)

        self.assertEqual([0, 1], survivors,
                         "a raising effect took the others down with it")

    def test_dispose_detaches(self):
        signal = reactive.Signal(0)
        runs = []
        eff = reactive.effect(lambda: runs.append(signal.get()))
        eff.dispose()
        signal.set(1)
        self.assertEqual([0], runs)


class PairingWindowTests(unittest.TestCase):
    def tearDown(self):
        store.pairing.set(None)
        store.pairing_left.set(0)

    def test_the_state_survives_while_the_window_is_open(self):
        store.pairing.set("z_1")
        store.apply_pairing_window(120)
        self.assertEqual("z_1", store.pairing.get())
        self.assertEqual(120, store.pairing_left.get())

    def test_the_state_ends_when_the_window_shuts(self):
        # Cleared only by tapping the button again until this existed, so
        # "searching for a device" outlived the coordinator's window.
        store.pairing.set("z_1")
        store.apply_pairing_window(120)

        store.apply_pairing_window(0)

        self.assertIsNone(store.pairing.get())


class GangStateTests(unittest.TestCase):
    """Moved from hwtest_ui: these never needed a board."""

    def tearDown(self):
        store.devices.set({})
        store.endpoints.set([])

    def test_each_gang_reads_its_own_endpoint(self):
        store.devices.set({IEEE: dict(TWO_GANG,
                                      endpoint_on_off={1: False, 2: True})})
        self.assertEqual(dev_common.STATE_OFF,
                         dev_common.device_state(gang(1)))
        self.assertEqual(dev_common.STATE_ON,
                         dev_common.device_state(gang(2)))

    def test_a_missing_cell_does_not_borrow_the_neighbour(self):
        # The Zigbee2MQTT failure in our shape: a silent fall back to the
        # shared value hands gang 1 whatever gang 2 last did.
        store.devices.set({IEEE: dict(TWO_GANG, on_off=True,
                                      endpoint_on_off={2: True})})
        self.assertEqual(dev_common.STATE_UNKNOWN,
                         dev_common.device_state(gang(1)))

    def test_a_single_gang_device_still_reads_device_wide(self):
        store.devices.set({IEEE: {"endpoints": [1],
                                  "clusters": {"1": [0, 3, 6]},
                                  "on_off": True}})
        self.assertEqual(dev_common.STATE_ON, dev_common.device_state(gang(1)))

    def test_unreachable_belongs_to_the_radio(self):
        store.devices.set({IEEE: dict(TWO_GANG, unreachable=True,
                                      endpoint_on_off={1: False, 2: True})})
        for endpoint in (1, 2):
            with self.subTest(endpoint=endpoint):
                self.assertEqual(dev_common.STATE_UNREACHABLE,
                                 dev_common.device_state(gang(endpoint)))

    def test_an_unknown_device_is_unknown(self):
        store.devices.set({})
        self.assertEqual(dev_common.STATE_UNKNOWN,
                         dev_common.device_state(gang(1)))

    def test_the_optimistic_write_lands_in_one_cell(self):
        store.devices.set({IEEE: dict(TWO_GANG,
                                      endpoint_on_off={1: False, 2: False})})
        # Only the optimistic write is under test, and it happens before the
        # command goes anywhere. Stubbing the dispatch keeps the assertion
        # about the store rather than about an api that is not here.
        sent = []
        saved = dev_common.bridge.dispatch
        dev_common.bridge.dispatch = (
            lambda api, op, params, on_ok=None, on_err=None: sent.append(op))
        try:
            dev_common.device_toggle(gang(1))
        finally:
            dev_common.bridge.dispatch = saved

        self.assertEqual(["control.send"], sent)

        self.assertEqual({1: True, 2: False},
                         store.devices.get()[IEEE]["endpoint_on_off"])
        self.assertEqual(dev_common.STATE_OFF,
                         dev_common.device_state(gang(2)),
                         "the neighbour row moved")


class VocabularyTests(unittest.TestCase):
    def test_the_tokens_are_distinct_and_named(self):
        tokens = (dev_common.STATE_ON, dev_common.STATE_OFF,
                  dev_common.STATE_UNKNOWN, dev_common.STATE_UNREACHABLE)
        self.assertEqual(4, len(set(tokens)))

    def test_this_module_carries_no_lvgl(self):
        # The whole point of the split: it is testable here only while it
        # imports nothing that needs a display.
        source = open(dev_common.__file__, encoding="utf-8").read()
        for forbidden in ("import lvgl", "import theme", "import toast"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
