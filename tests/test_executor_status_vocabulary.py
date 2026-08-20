"""The executor's outcome vocabulary: one source, and a policy built from it.

Two different things are pinned here, and they fail for different reasons.

  * The *vocabulary* -- the four names and their values -- belongs to the
    Executor, which is what produces them. The values leave this process (they
    travel over REST, and the panel's own UI reads them straight off the
    result), so they are a contract rather than an internal detail: renaming
    one is a breaking change and should have to be a deliberate one.
  * The *policy* -- which outcomes mean "do not send this again" -- belongs to
    the Scheduler. It is asserted here by driving real ticks, not by reading
    the tuple back, because the tuple agreeing with itself proves nothing.

The source-text checks are here for a failure a behavioural test cannot see. A
constant that is declared and then ignored in favour of the identical string
literal passes every runtime assertion ever written while handing back exactly
the duplication it was introduced to remove. Only reading the source catches
that, so these read the source.

``ack_unjournaled`` is the outcome the whole exercise turns on: the ack came
back and the device really did act, and only the journal write failed. The
scheduler used to treat it as unfinished and re-send it every tick -- roughly
240 times across a two-hour window -- so a user who switched a light off by
hand watched it come back on within TICK_SECONDS.
"""

import asyncio
import io
import os
import shutil
import sys
import unittest
from pathlib import Path

from smart_kosher.application import scheduler
from smart_kosher.application.control_service import ControlService
from smart_kosher.application.executor import (
    ACK_UNJOURNALED,
    ALREADY_EXECUTED,
    EXECUTED,
    FAILED,
)
from smart_kosher.ports.device_gateway import GATEWAY_ALL_STATUSES

sys.path.insert(
    0,
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "products", "panel", "device"),
)

import brain  # noqa: E402  (needs the path insert above)

ROOT = Path(__file__).resolve().parents[1]
EXECUTOR_SRC = ROOT / "src" / "smart_kosher" / "application" / "executor.py"
SCHEDULER_SRC = ROOT / "src" / "smart_kosher" / "application" / "scheduler.py"

TEMP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_vocab_tmp")

LOCAL_HOUR = 8
FIRE_UTC = (2026, 1, 15, 6, 0)

# name -> wire value. The names are what callers import; the values are what
# other processes see.
VOCABULARY = {
    "EXECUTED": EXECUTED,
    "ALREADY_EXECUTED": ALREADY_EXECUTED,
    "ACK_UNJOURNALED": ACK_UNJOURNALED,
    "FAILED": FAILED,
}


def _read(path):
    return io.open(str(path), encoding="utf-8").read()


class FakeClock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


def _schedule(target_id, **overrides):
    data = {
        "name": "בדיקה",
        "enabled": True,
        "target_type": "endpoint",
        "target_id": target_id,
        "action_type": "on",
        "action_data": {},
        "trigger_type": "fixed_time",
        "trigger_data": {"h": LOCAL_HOUR, "m": 0},
        "recurrence_type": "daily",
        "recurrence_data": {},
    }
    data.update(overrides)
    return data


class VocabularyValueTests(unittest.TestCase):
    """The values themselves, which are a cross-process contract."""

    def test_each_status_has_its_wire_value(self):
        self.assertEqual("executed", EXECUTED)
        self.assertEqual("already_executed", ALREADY_EXECUTED)
        self.assertEqual("ack_unjournaled", ACK_UNJOURNALED)
        self.assertEqual("failed", FAILED)

    def test_the_four_statuses_are_distinct(self):
        self.assertEqual(4, len(set(VOCABULARY.values())))

    def test_the_executor_vocabulary_is_not_the_gateway_vocabulary(self):
        # ports/device_gateway.py answers "how far did this travel on the
        # wire"; these answer "what did the brain conclude". The task list
        # calls out merging the two by name. Overlap is the first symptom.
        self.assertEqual(
            set(), set(VOCABULARY.values()) & set(GATEWAY_ALL_STATUSES),
            "an executor status collided with a gateway status")


class SingleSourceTests(unittest.TestCase):
    """That the constants are load-bearing, not decorative."""

    def test_executor_states_each_status_literal_exactly_once(self):
        source = _read(EXECUTOR_SRC)
        for name, value in sorted(VOCABULARY.items()):
            with self.subTest(status=name):
                self.assertEqual(
                    1, source.count('"{}"'.format(value)),
                    "{} should appear once in executor.py -- in its own "
                    "declaration. A second occurrence is a return point that "
                    "went back to a literal, which a behavioural test cannot "
                    "see.".format(value))

    def test_executor_returns_the_constants_at_every_exit(self):
        source = _read(EXECUTOR_SRC)
        # Every status a caller receives is set through the names.
        for name in sorted(VOCABULARY):
            with self.subTest(status=name):
                self.assertIn('"status": {},'.format(name), source)

    def test_scheduler_builds_its_policy_from_the_imported_names(self):
        bindings = [ln for ln in _read(SCHEDULER_SRC).splitlines()
                    if ln.strip().startswith("_SETTLED")]
        self.assertEqual(1, len(bindings),
                         "expected exactly one _SETTLED binding")
        settled = bindings[0]
        self.assertNotIn('"', settled,
                         "_SETTLED restated a status as a literal")
        for name in ("EXECUTED", "ALREADY_EXECUTED", "ACK_UNJOURNALED"):
            self.assertIn(name, settled)

    def test_the_policy_set_is_named_for_policy_not_for_the_journal(self):
        # ack_unjournaled is by definition the outcome that did *not* reach the
        # journal, so a name built on "journalled" is false for its own member.
        self.assertNotIn("_JOURNALLED", _read(SCHEDULER_SRC))


class SettledPolicyTests(unittest.TestCase):
    """The policy, driven through real ticks against the panel composition."""

    def setUp(self):
        shutil.rmtree(TEMP_DIR, ignore_errors=True)
        os.makedirs(TEMP_DIR)
        self.composed = brain.create(data_dir=TEMP_DIR, clock=None)
        self.gateway = self.composed.gateway
        self.endpoint = self._run(self.composed.api.dispatch("endpoints.create", {
            "data": {"name": "תאורה", "ieee_address": "0x1122334455667788",
                     "zigbee_endpoint": 1},
        }))

    def tearDown(self):
        shutil.rmtree(TEMP_DIR, ignore_errors=True)

    @staticmethod
    def _run(coro):
        return asyncio.run(coro)

    def _add_schedule(self, **overrides):
        return self._run(self.composed.api.dispatch("schedules.create", {
            "data": _schedule(self.endpoint["id"], **overrides),
        }))

    def _break_the_journal(self):
        def refuse(event, outcome):
            raise OSError("flash full")
        self.composed.executor.journal.record = refuse

    def test_an_ack_that_missed_the_journal_is_not_sent_again(self):
        self._add_schedule()
        self._break_the_journal()
        clock = FakeClock(FIRE_UTC)
        sched = scheduler.Scheduler.for_brain(self.composed, clock=clock)

        outcomes = self._run(sched.tick())
        self.assertEqual([ACK_UNJOURNALED], [o["status"] for o in outcomes])
        self.assertEqual(1, len(self.gateway.commands))

        # The device acted. The journal cannot say so and never will, so the
        # only thing standing between the user and a light that switches
        # itself back on is the scheduler declining to rewind.
        clock.now = (2026, 1, 15, 6, 1)
        self._run(sched.tick())
        self.assertEqual(
            1, len(self.gateway.commands),
            "the device was commanded a second time; a user who switched it "
            "off by hand would see it come back")

    def test_a_failed_event_is_still_retried(self):
        # The other half: quieting ack_unjournaled must not quiet `failed`,
        # where the device really did not act.
        self._add_schedule()
        for _ in range(3):        # exhaust the Executor's own retries
            self.gateway.queue_response("error")
        clock = FakeClock(FIRE_UTC)
        sched = scheduler.Scheduler.for_brain(self.composed, clock=clock)

        outcomes = self._run(sched.tick())
        self.assertEqual([FAILED], [o["status"] for o in outcomes])

        clock.now = (2026, 1, 15, 6, 1)
        outcomes = self._run(sched.tick())
        self.assertEqual([EXECUTED], [o["status"] for o in outcomes],
                         "a failed event must stay in view of the next tick")

    def test_manual_control_gates_its_confirmation_on_the_constant(self):
        # control_service gates its confirmation read on EXECUTED. Pin that a
        # normal manual send still reports through the shared vocabulary.
        service = ControlService(self.composed.executor,
                                 self.composed.repository)
        outcome = self._run(service.send("endpoint", self.endpoint["id"], "on"))
        self.assertEqual(EXECUTED, outcome["status"])
