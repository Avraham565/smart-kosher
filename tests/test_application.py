import asyncio
import unittest
import os
import shutil

from smart_kosher.adapters import (
    H2Simulator,
    JsonEventJournal,
    JsonRepository,
    MemoryEventJournal,
    MemoryRepository,
)
from smart_kosher.application.executor import Executor
from smart_kosher.application.planner import Planner, PlannerConfig
from smart_kosher.application.recovery import RecoveryService


def schedule():
    return {
        "id": "schedule-1",
        "enabled": True,
        "target_type": "group",
        "target_id": "all",
        "action_type": "on",
        "action_data": {},
        "trigger_type": "fixed_time",
        "trigger_data": {"h": 12, "m": 0},
        "recurrence_type": "daily",
        "recurrence_data": {},
    }


def event():
    return {
        "event_id": "event-1",
        "schedule_id": "schedule-1",
        "source_date": (2026, 6, 8),
        "utc_minute": 100,
        "target_type": "group",
        "target_id": "all",
        "action_type": "on",
        "action_data": {},
    }


class ExecutorTests(unittest.TestCase):
    def test_retries_timeout_then_records_ack(self):
        gateway = H2Simulator(["timeout", "sent_to_zigbee"])
        journal = MemoryEventJournal()
        outcome = asyncio.run(Executor(gateway, journal, max_attempts=3).execute(event()))
        self.assertEqual("executed", outcome["status"])
        self.assertEqual(2, outcome["attempts"])
        self.assertEqual(2, len(gateway.commands))
        self.assertTrue(journal.was_executed("event-1"))

    def test_already_executed_event_is_not_sent_again(self):
        gateway = H2Simulator()
        journal = MemoryEventJournal()
        executor = Executor(gateway, journal)
        asyncio.run(executor.execute(event()))
        outcome = asyncio.run(executor.execute(event()))
        self.assertEqual("already_executed", outcome["status"])
        self.assertEqual(1, len(gateway.commands))

    def test_failed_event_is_not_recorded(self):
        gateway = H2Simulator(["timeout", "error"])
        journal = MemoryEventJournal()
        outcome = asyncio.run(Executor(gateway, journal, max_attempts=2).execute(event()))
        self.assertEqual("failed", outcome["status"])
        self.assertFalse(journal.was_executed("event-1"))

    def test_accepted_by_h2_is_not_recorded_as_executed(self):
        gateway = H2Simulator(["accepted_by_h2"])
        journal = MemoryEventJournal()
        outcome = asyncio.run(Executor(gateway, journal, max_attempts=1).execute(event()))
        self.assertEqual("failed", outcome["status"])
        self.assertFalse(journal.was_executed("event-1"))

    def test_ack_with_journal_failure_is_not_retried(self):
        class FailingJournal:
            @staticmethod
            def was_executed(event_id):
                return False

            @staticmethod
            def record(current_event, result):
                raise OSError("disk full")

        gateway = H2Simulator()
        outcome = asyncio.run(Executor(gateway, FailingJournal(), max_attempts=3).execute(event()))
        self.assertEqual("ack_unjournaled", outcome["status"])
        self.assertEqual(1, len(gateway.commands))


class RecoveryTests(unittest.TestCase):
    def test_recovery_plans_and_executes_missed_event_once(self):
        repository = MemoryRepository({"schedules": [schedule()]})
        planner = Planner(PlannerConfig(31.7683, 35.2137), repository)
        gateway = H2Simulator()
        executor = Executor(gateway, MemoryEventJournal())
        recovery = RecoveryService(planner, executor)

        first = asyncio.run(
            recovery.recover((2026, 6, 8, 9, 59), (2026, 6, 8, 10, 1)))
        second = asyncio.run(
            recovery.recover((2026, 6, 8, 9, 59), (2026, 6, 8, 10, 1)))
        self.assertEqual(1, first["event_count"])
        self.assertEqual("executed", first["outcomes"][0]["status"])
        self.assertEqual("already_executed", second["outcomes"][0]["status"])
        self.assertEqual(1, len(gateway.commands))

    def test_persistent_journal_prevents_replay_after_reboot(self):
        base = os.path.join("tests", ".tmp-recovery")
        if os.path.exists(base):
            shutil.rmtree(base)
        try:
            first_repository = JsonRepository(base)
            first_repository.upsert("schedules", schedule())
            first_gateway = H2Simulator()
            first_recovery = RecoveryService(
                Planner(PlannerConfig(31.7683, 35.2137), first_repository),
                Executor(first_gateway, JsonEventJournal(first_repository)),
            )
            asyncio.run(first_recovery.recover(
                (2026, 6, 8, 9, 59), (2026, 6, 8, 10, 1)))
            self.assertEqual(1, len(first_gateway.commands))

            rebooted_repository = JsonRepository(base)
            rebooted_gateway = H2Simulator()
            rebooted_recovery = RecoveryService(
                Planner(PlannerConfig(31.7683, 35.2137), rebooted_repository),
                Executor(rebooted_gateway, JsonEventJournal(rebooted_repository)),
            )
            result = asyncio.run(rebooted_recovery.recover(
                (2026, 6, 8, 9, 59),
                (2026, 6, 8, 10, 1),
            ))
            self.assertEqual("already_executed", result["outcomes"][0]["status"])
            self.assertEqual([], rebooted_gateway.commands)
        finally:
            if os.path.exists(base):
                shutil.rmtree(base)


class FakeSettableClock:
    def __init__(self):
        self.set_calls = []

    def set_utc(self, year, month, day, hour, minute, second):
        self.set_calls.append((year, month, day, hour, minute, second))


class DeviceTimeServiceTests(unittest.TestCase):
    def _service(self, clock=None):
        from smart_kosher.application.device_time import DeviceTimeService
        return DeviceTimeService(clock)

    def _fields(self, **overrides):
        fields = {"year": 2026, "month": 7, "day": 8,
                  "hour": 16, "minute": 30, "second": 0}
        fields.update(overrides)
        return fields

    def test_sets_clock_and_returns_formatted_time(self):
        clock = FakeSettableClock()
        result = self._service(clock).set_time(self._fields())
        self.assertEqual([(2026, 7, 8, 16, 30, 0)], clock.set_calls)
        self.assertEqual("2026-07-08 16:30:00", result)

    def test_no_clock_raises_unsupported(self):
        from smart_kosher.application.device_time import ClockUnsupportedError
        with self.assertRaises(ClockUnsupportedError):
            self._service(None).set_time(self._fields())

    def test_validation_happens_before_clock_check(self):
        # A platform without an RTC must still report bad input as invalid
        # (ValueError -> 400), not as unsupported (501).
        with self.assertRaises(ValueError):
            self._service(None).set_time(self._fields(month=13))

    def test_impossible_date_rejected_without_touching_clock(self):
        clock = FakeSettableClock()
        with self.assertRaises(ValueError):
            self._service(clock).set_time(self._fields(month=2, day=30))
        self.assertEqual([], clock.set_calls)


if __name__ == "__main__":
    unittest.main()
