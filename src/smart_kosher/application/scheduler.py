# The scheduler loop -- the piece that makes a saved schedule actually fire.
#
# Everything downstream already existed and is proven: Planner turns schedules
# into dated events, Executor sends them through the gateway, and the persistent
# JsonEventJournal de-duplicates by event_id. What was missing is the thing that
# calls them on a clock. That is this module, and nothing else here does I/O
# beyond the executor's gateway hop -- no LVGL, so it is fully testable on
# CPython (tests/test_panel_scheduler.py).
#
# It lived in the panel's own directory until 2026-08-05, which made automation a property of
# one product's UI folder rather than of the brain: the headless hub imports the
# same brain but could not reach this file, so schedules saved there were stored
# and never fired. It depends on nothing above the application layer, so this is
# where it belongs. Starting it is still each entry point's job -- one task on
# whatever loop that product already runs.
#
# Two properties carry the whole design:
#
#   * event_id is deterministic (schedule + date + minute) and the journal
#     survives reboots. So *replaying* a window is free of side effects: an
#     event already sent is reported "already_executed" and never sent twice.
#     That is why we never persist a "last seen" marker -- a bounded look-back
#     window plus journal dedup is both correct and simpler. Boot catch-up and a
#     normal tick are therefore the *same* operation, and share one code path
#     (RecoveryService) rather than two that can drift apart.
#
#   * The window is (start_exclusive, end_inclusive] in whole UTC minutes, so
#     ticks tile the timeline without gaps or double-planning even when a tick
#     runs late (a long zmanim computation, a slow H2 round trip).
#
# The clock is the RTC, in UTC (PCF8563 -> machine.RTC at boot; time.set writes
# both). Until it is set the panel reads year 2000 -- every planned time would be
# wrong, so we fire nothing and do not advance, and the first tick after the user
# sets the clock does the catch-up.

import asyncio

from ..ports.clock import MIN_VALID_YEAR
from ..zmanim import gregorian_from_day_number
from .planner import Planner
from .recovery import RecoveryService
from .views import now_utc, planner_config, settings_key

# 30s keeps the worst-case lateness of a minute-precision trigger under a
# minute, at a cost of one cheap "no new minute" check most of the time.
TICK_SECONDS = 30

# How far back a tick may reach. This bounds boot catch-up (power cut on Friday
# afternoon -> the Shabbat lights still come on when power returns) and any
# stalled tick. Deliberately far below the planner's 2880-minute ceiling: the
# panel's journal keeps only its last 128 records (brain._JOURNAL_MAX_RECORDS),
# and dedup is only trustworthy inside that history.
CATCH_UP_MINUTES = 120

# The first tick is the expensive one: the planner spans +/-3 days around the
# window, so it computes a week of zmanim before its day-cache is warm (later
# ticks are ~50x cheaper). That is a single cooperative block with no await in
# it, and the loop cannot pump LVGL meanwhile -- so let the boot render and the
# first status/clock refresh finish first. Costs nothing: catch-up looks back
# two hours regardless of when it runs.
START_DELAY_SECONDS = 5


def timestamp_from_minute(total_minute):
    """Inverse of :meth:`Planner.utc_minute`: absolute minute -> UTC 5-tuple."""
    year, month, day = gregorian_from_day_number(total_minute // 1440)
    minute_of_day = total_minute % 1440
    return (year, month, day, minute_of_day // 60, minute_of_day % 60)


def plan_window(last, now, catch_up_minutes):
    """The ``(start_exclusive, end_inclusive]`` window a tick should fire.

    Pure and clock-free, so every branch below is unit-testable:

    * ``last is None`` (first tick after boot) -> look back ``catch_up_minutes``
      and let the journal discard whatever already ran before the reboot.
    * A tick that ran late -> the window stretches back to ``last``, so nothing
      is skipped; it is clamped to ``catch_up_minutes`` because the planner
      refuses windows wider than its ceiling.
    * No new minute yet, or the clock moved backwards (a time.set correction)
      -> ``None``: there is nothing meaningful to plan and the caller re-anchors.
    """
    end_minute = Planner.utc_minute(now)
    if last is None:
        start_minute = end_minute - catch_up_minutes
    else:
        start_minute = Planner.utc_minute(last)
        if start_minute >= end_minute:
            return None
        if end_minute - start_minute > catch_up_minutes:
            start_minute = end_minute - catch_up_minutes
    return timestamp_from_minute(start_minute), now


class Scheduler:
    """Fires due schedules on the panel's asyncio loop.

    Composed from the brain's own pieces (``Scheduler.for_brain``) but holding
    its *own* Planner: ViewService memoizes a planner too, for the "upcoming"
    view, and sharing it would let a UI page's day-cache and error list bleed
    into firing decisions. Planners are cheap to keep and expensive to build, so
    each owner keeps one.
    """

    def __init__(self, repository, settings, executor,
                 tick_seconds=TICK_SECONDS, catch_up_minutes=CATCH_UP_MINUTES,
                 start_delay_seconds=START_DELAY_SECONDS, clock=None):
        self.repository = repository
        self.settings = settings
        self.executor = executor
        self.tick_seconds = tick_seconds
        self.catch_up_minutes = catch_up_minutes
        self.start_delay_seconds = start_delay_seconds
        # Injectable purely so tests can drive time; on the panel this reads the
        # RTC through time.gmtime().
        self._clock = now_utc if clock is None else clock
        self._recovery = None
        self._recovery_key = None
        self._last = None

    @classmethod
    def for_brain(cls, composed, **kwargs):
        """Build from an already-composed application.

        ``composed`` is anything exposing ``repository``, ``settings`` and
        ``executor`` -- duck-typed rather than imported, so this stays free of
        any one product's composition root (the panel's brain.Brain today).
        Sharing the *executor* is the load-bearing part: the schedule path and
        the UI's manual-control path must go through the same journal, or a tap
        and a schedule can double-send or lose each other's dedup history.
        """
        return cls(composed.repository, composed.settings, composed.executor,
                   **kwargs)

    def _recovery_for(self, settings):
        """One RecoveryService per settings generation.

        PlannerConfig runs a full zmanim computation on construction and the
        planner caches a day of zmanim, so we reuse it -- but a change of city,
        UTC offset or candle offset moves every zman, so the key change rebuilds
        it (same contract as ViewService._planner_for).
        """
        key = settings_key(settings)
        if self._recovery is None or self._recovery_key != key:
            planner = Planner(planner_config(settings), self.repository)
            self._recovery = RecoveryService(
                planner, self.executor,
                max_catch_up_minutes=self.catch_up_minutes,
            )
            self._recovery_key = key
        return self._recovery

    # An event the Executor journalled is finished; anything else has not
    # actually reached its device and must stay in view of the next tick.
    _JOURNALLED = ("executed", "already_executed")

    def _advance_to(self, now, result):
        """Where the next window should start, given how this one went.

        Moving straight to ``now`` regardless of outcome was wrong: the journal
        only records successes, so the minute holding a failed event simply
        left the window and the event was never attempted again -- until a
        reboot happened to fall inside the catch-up span. That quietly undid
        the point of not journalling unproven commands.

        Rewinding to just before the earliest unfinished event means the retry
        keeps happening every tick. It cannot run away: the window clamp caps
        the look-back, so a device that stays unreachable is retried for
        catch_up_minutes and then dropped rather than forever.
        """
        pending = [
            event["utc_minute"]
            for event, outcome in zip(result["events"], result["outcomes"])
            if outcome.get("status") not in self._JOURNALLED
        ]
        if not pending:
            return now
        retry_from = min(pending) - 1
        if retry_from >= Planner.utc_minute(now):
            return now
        print("scheduler: {} event(s) unfinished, retrying from {}".format(
            len(pending), retry_from))
        return timestamp_from_minute(retry_from)

    async def tick(self):
        """Plan and fire one window. Returns the executor outcomes."""
        now = self._clock()
        if now[0] < MIN_VALID_YEAR:
            # Clock never set: firing now would act on garbage times. Leave
            # ``_last`` at None so the first tick after time.set catches up.
            return []

        window = plan_window(self._last, now, self.catch_up_minutes)
        if window is None:
            self._last = now
            return []

        recovery = self._recovery_for(self.settings.get())
        result = await recovery.recover(window[0], window[1])
        # Advance only past what actually got through. If the planner threw we
        # never reach here and the next tick retries the same span; if an event
        # ran but was not journaled, we rewind to just before it so the next
        # tick sweeps it up again.
        self._last = self._advance_to(now, result)

        for outcome in result["outcomes"]:
            print("scheduler:", outcome["event_id"], "->", outcome["status"])
        # A schedule that fails validation is skipped silently by the planner --
        # exactly the "saved but never fires" symptom, so surface it on serial.
        if recovery.planner.last_errors:
            print("scheduler: unplannable schedules:",
                  recovery.planner.last_errors)
        return result["outcomes"]

    async def run(self):
        """The forever task. A tick must never kill the loop: a raise here
        would leave the panel rendering happily with automation dead and no
        symptom, which is the failure mode this whole module exists to end."""
        await asyncio.sleep(self.start_delay_seconds)
        while True:
            try:
                await self.tick()
            except Exception as exc:
                print("scheduler tick failed:", exc)
            await asyncio.sleep(self.tick_seconds)
