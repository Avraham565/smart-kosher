"""The scheduler on CPython, against product A's real composition.

The scheduler is the piece that makes a saved schedule fire. It lives in the
brain now (smart_kosher.application.scheduler) and is imported normally; these
tests drive it against the panel's actual in-process composition
(panel_mp/brain.py + the H2 simulator) with an injected clock, which is as
close to the device as we get without hardware.

The path insert is only for ``brain`` -- panel_mp lives at the board root
rather than in the installed package. It imports no LVGL, which is what makes
running it here possible.
"""

import asyncio
import os
import shutil
import sys
import unittest

from smart_kosher.application import scheduler
from smart_kosher.application.planner import Planner

sys.path.insert(
    0,
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "panel_mp"),
)

import brain  # noqa: E402  (needs the path insert above)

TEMP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_panel_tmp")

# Mid-January: Israel is on standard time (UTC+2), so a local 08:00 trigger is
# 06:00 UTC on every day of these tests -- no DST edge to reason about.
LOCAL_HOUR = 8
FIRE_UTC = (2026, 1, 15, 6, 0)


class FakeClock:
    """The RTC stand-in: a UTC 5-tuple the test moves by hand."""

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


class PlanWindowTests(unittest.TestCase):
    """The pure window arithmetic -- every tick's correctness rests on it."""

    def test_timestamp_from_minute_inverts_utc_minute(self):
        for stamp in ((2026, 1, 1, 0, 0), (2026, 1, 15, 6, 0), (2026, 12, 31, 23, 59)):
            minute = Planner.utc_minute(stamp)
            self.assertEqual(stamp, scheduler.timestamp_from_minute(minute))

    def test_first_tick_looks_back_the_catch_up_window(self):
        start, end = scheduler.plan_window(None, (2026, 1, 15, 7, 0), 120)
        self.assertEqual((2026, 1, 15, 5, 0), start)
        self.assertEqual((2026, 1, 15, 7, 0), end)

    def test_normal_tick_spans_exactly_since_last(self):
        start, end = scheduler.plan_window((2026, 1, 15, 6, 59), (2026, 1, 15, 7, 0), 120)
        self.assertEqual((2026, 1, 15, 6, 59), start)
        self.assertEqual((2026, 1, 15, 7, 0), end)

    def test_late_tick_is_clamped_to_the_catch_up_window(self):
        # A day-long stall: without the clamp the planner refuses the window.
        start, _ = scheduler.plan_window((2026, 1, 14, 7, 0), (2026, 1, 15, 7, 0), 120)
        self.assertEqual((2026, 1, 15, 5, 0), start)

    def test_same_minute_plans_nothing(self):
        self.assertIsNone(
            scheduler.plan_window((2026, 1, 15, 7, 0), (2026, 1, 15, 7, 0), 120))

    def test_clock_moved_backwards_plans_nothing(self):
        self.assertIsNone(
            scheduler.plan_window((2026, 1, 15, 7, 0), (2026, 1, 15, 6, 30), 120))

    def test_window_crosses_midnight(self):
        start, end = scheduler.plan_window(None, (2026, 1, 15, 0, 30), 120)
        self.assertEqual((2026, 1, 14, 22, 30), start)
        self.assertEqual((2026, 1, 15, 0, 30), end)


class SchedulerTests(unittest.TestCase):
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

    def _scheduler(self, clock, **kwargs):
        return scheduler.Scheduler.for_brain(self.composed, clock=clock, **kwargs)

    def test_due_schedule_is_sent_once_and_never_again(self):
        self._add_schedule()
        clock = FakeClock((2026, 1, 15, 5, 59))
        sched = self._scheduler(clock)

        # First tick anchors and catches up the (empty) two hours before 05:59.
        self._run(sched.tick())
        self.assertEqual([], self.gateway.commands)

        clock.now = FIRE_UTC
        outcomes = self._run(sched.tick())
        self.assertEqual(["executed"], [o["status"] for o in outcomes])
        self.assertEqual(1, len(self.gateway.commands))
        self.assertEqual("on", self.gateway.commands[0]["action_type"])
        self.assertEqual(self.endpoint["id"], self.gateway.commands[0]["target_id"])

        # A tick a minute later re-plans an overlapping span; the journal makes
        # the replay a no-op rather than a second relay click.
        clock.now = (2026, 1, 15, 6, 1)
        outcomes = self._run(sched.tick())
        self.assertEqual([], outcomes)
        self.assertEqual(1, len(self.gateway.commands))

    def test_boot_catch_up_fires_an_event_missed_while_powered_off(self):
        self._add_schedule()
        # Panel comes up at 07:00 having been off since before 06:00.
        sched = self._scheduler(FakeClock((2026, 1, 15, 7, 0)))
        outcomes = self._run(sched.tick())
        self.assertEqual(["executed"], [o["status"] for o in outcomes])
        self.assertEqual(1, len(self.gateway.commands))

    def test_a_failed_event_is_retried_on_the_next_tick(self):
        # The journal only records successes, so advancing past a failed
        # minute dropped the event entirely -- it would only ever be retried
        # if a reboot happened to land inside the catch-up span. That undid
        # the point of refusing to journal unproven commands.
        self._add_schedule()
        for _ in range(3):    # exhaust the Executor's own retries
            self.gateway.queue_response("error")
        clock = FakeClock(FIRE_UTC)
        sched = self._scheduler(clock)

        outcomes = self._run(sched.tick())
        self.assertEqual(["failed"], [o["status"] for o in outcomes])

        clock.now = (2026, 1, 15, 6, 1)           # a normal minute later
        outcomes = self._run(sched.tick())
        self.assertEqual(["executed"], [o["status"] for o in outcomes],
                         "the failed event was never attempted again")

    def test_a_succeeding_event_is_not_retried(self):
        self._add_schedule()
        clock = FakeClock(FIRE_UTC)
        sched = self._scheduler(clock)
        self.assertEqual(["executed"], [o["status"] for o in self._run(sched.tick())])

        clock.now = (2026, 1, 15, 6, 1)
        self.assertEqual([], self._run(sched.tick()))
        self.assertEqual(1, len(self.gateway.commands))

    def test_a_permanently_failing_event_stops_after_the_catch_up_window(self):
        # Retrying forever would mean a dead device keeps a schedule alive for
        # days. The window clamp has to bound it.
        self._add_schedule()
        for _ in range(40):
            self.gateway.queue_response("error")
        clock = FakeClock(FIRE_UTC)
        sched = self._scheduler(clock, catch_up_minutes=5)

        self._run(sched.tick())
        clock.now = (2026, 1, 15, 6, 30)          # well past the 5-minute clamp
        self._run(sched.tick())
        self.assertLessEqual(
            Planner.utc_minute(sched._last) - Planner.utc_minute(clock.now), 0)
        clock.now = (2026, 1, 15, 6, 31)
        self.assertEqual([], self._run(sched.tick()),
                         "an event older than the window must fall out")

    def test_boot_catch_up_does_not_replay_what_already_fired(self):
        self._add_schedule()
        self._run(self._scheduler(FakeClock(FIRE_UTC)).tick())
        self.assertEqual(1, len(self.gateway.commands))

        # A reboot builds a fresh Scheduler with no memory of ``last`` -- only
        # the persisted journal stops the relay from clicking twice.
        reborn = self._scheduler(FakeClock((2026, 1, 15, 6, 30)))
        outcomes = self._run(reborn.tick())
        self.assertEqual(["already_executed"], [o["status"] for o in outcomes])
        self.assertEqual(1, len(self.gateway.commands))

    def test_unset_rtc_fires_nothing_and_keeps_the_catch_up_intact(self):
        self._add_schedule()
        clock = FakeClock((2000, 1, 1, 0, 0))       # machine.RTC before time.set
        sched = self._scheduler(clock)
        self.assertEqual([], self._run(sched.tick()))
        self.assertEqual([], self.gateway.commands)

        # After the user sets the clock, the very next tick must still catch up
        # -- the unset ticks must not have consumed the look-back anchor.
        clock.now = (2026, 1, 15, 7, 0)
        self._run(sched.tick())
        self.assertEqual(1, len(self.gateway.commands))

    def test_long_stall_is_clamped_instead_of_raising(self):
        self._add_schedule()
        clock = FakeClock(FIRE_UTC)
        sched = self._scheduler(clock)
        self._run(sched.tick())
        self.assertEqual(1, len(self.gateway.commands))

        # Five days later: far beyond the planner's max window, which would
        # raise if the clamp were missing. Only the newest day is in range.
        clock.now = (2026, 1, 20, 7, 0)
        outcomes = self._run(sched.tick())
        self.assertEqual(["executed"], [o["status"] for o in outcomes])
        self.assertEqual(2, len(self.gateway.commands))

    def test_disabled_schedule_does_not_fire(self):
        created = self._add_schedule()
        self._run(self.composed.api.dispatch(
            "schedules.set_enabled", {"id": created["id"], "enabled": False}))
        self._run(self._scheduler(FakeClock((2026, 1, 15, 7, 0))).tick())
        self.assertEqual([], self.gateway.commands)

    def test_zman_schedule_fires_at_its_computed_minute(self):
        # Proves the zmanim path, not just wall-clock triggers: plan the day,
        # then set the clock to the minute the planner itself chose.
        self._add_schedule(trigger_type="zman", trigger_data={"zman": "shkia"})
        sched = self._scheduler(FakeClock((2026, 1, 15, 12, 0)))
        planner = sched._recovery_for(self.composed.settings.get()).planner
        events = planner.events_between((2026, 1, 15, 0, 0), (2026, 1, 15, 23, 59),
                                        max_window_minutes=1440)
        self.assertEqual(1, len(events))

        sched = self._scheduler(FakeClock(
            scheduler.timestamp_from_minute(events[0]["utc_minute"])))
        self.assertEqual(["executed"], [o["status"] for o in self._run(sched.tick())])
        self.assertEqual(1, len(self.gateway.commands))

    def test_planner_is_rebuilt_only_when_settings_change(self):
        sched = self._scheduler(FakeClock(FIRE_UTC))
        first = sched._recovery_for(self.composed.settings.get())
        self.assertIs(first, sched._recovery_for(self.composed.settings.get()))

        # A different city moves every zman, so the cached planner must go.
        self._run(self.composed.api.dispatch(
            "settings.update", {"data": {"lat": 32.0853, "lon": 34.7818,
                                         "city": "תל אביב"}}))
        self.assertIsNot(first, sched._recovery_for(self.composed.settings.get()))

    def test_unplannable_schedule_is_reported_and_does_not_break_the_tick(self):
        # JsonRepository rejects an invalid schedule on write *and* refuses to
        # load a collection containing one, so this row cannot come from the
        # panel's own storage -- the planner's tolerance is defence in depth.
        # Feed it through a repository that does not validate, which is the
        # only level where the behaviour is reachable, and assert the healthy
        # schedule beside it still fires.
        good = _schedule(self.endpoint["id"])
        good["id"] = "good-1"
        broken = _schedule(self.endpoint["id"], trigger_data={"h": 99, "m": 0})
        broken["id"] = "broken-1"

        sched = scheduler.Scheduler(
            _StubRepository([good, broken]), self.composed.settings,
            self.composed.executor, clock=FakeClock((2026, 1, 15, 7, 0)))
        self.assertEqual(["executed"], [o["status"] for o in self._run(sched.tick())])
        errors = sched._recovery_for(self.composed.settings.get()).planner.last_errors
        self.assertEqual(["broken-1"], [e["schedule_id"] for e in errors])


class _StubRepository:
    """The narrow slice of the repository port the Planner actually reads."""

    def __init__(self, schedules):
        self._schedules = schedules

    def get_all(self, entity_type):
        return self._schedules if entity_type == "schedules" else []


if __name__ == "__main__":
    unittest.main()
