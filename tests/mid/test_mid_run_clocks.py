"""Mid-tier selections. Write or run only in an explicitly requested testing task."""
from __future__ import annotations

import test_run_clocks as _support
from test_run_clocks import (
    RunClockTests,
    RunClocks,
    unittest,
)


class RunClockTests(_support.RunClockTests):
# TEST-TIER-BEGIN tests/test_run_clocks.py::RunClockTests.test_start_budget_spans_individual_startup_requests
    def test_start_budget_spans_individual_startup_requests(self) -> None:
        clock = RunClocks(10, 60, None)
        self.assertIsNone(clock.check(69.9, 69, False))
        error = clock.check(70, 69, False)
        assert error is not None
        self.assertEqual(error.result["code"], "limit_reached")
        self.assertEqual(error.result["detail"], {"basis": "fields", "limit": "start"})
        clock.acknowledge(70)
        self.assertIsNone(clock.check(71, 70, False))
# TEST-TIER-END tests/test_run_clocks.py::RunClockTests.test_start_budget_spans_individual_startup_requests

# TEST-TIER-BEGIN tests/test_run_clocks.py::RunClockTests.test_any_notification_resets_idle_and_zero_disables_it
    def test_any_notification_resets_idle_and_zero_disables_it(self) -> None:
        clock = RunClocks(0, 60, {"idleSeconds": 3})
        clock.acknowledge(1)
        for at in (3, 5, 7):
            self.assertIsNone(clock.check(at, at - 1, False))
        error = clock.check(9, 6, False)
        assert error is not None
        self.assertEqual(error.result["detail"], {"basis": "fields", "limit": "idle"})
        off = RunClocks(0, 60, {"idleSeconds": 0})
        off.acknowledge(1)
        self.assertIsNone(off.check(100000, 1, False))
# TEST-TIER-END tests/test_run_clocks.py::RunClockTests.test_any_notification_resets_idle_and_zero_disables_it

# TEST-TIER-BEGIN tests/test_run_clocks.py::RunClockTests.test_running_call_and_background_work_preserve_idle_budget
    def test_running_call_and_background_work_preserve_idle_budget(self) -> None:
        clock = RunClocks(0, 60, {"idleSeconds": 3})
        clock.acknowledge(1)
        self.assertIsNone(clock.check(2, 1, True))
        self.assertIsNone(clock.check(200, 1, True))
        self.assertIsNone(clock.check(201, 1, False))
        self.assertIsNone(clock.check(202, 1, False))
        self.assertIsNotNone(clock.check(203, 1, False))
# TEST-TIER-END tests/test_run_clocks.py::RunClockTests.test_running_call_and_background_work_preserve_idle_budget

# TEST-TIER-BEGIN tests/test_run_clocks.py::RunClockTests.test_total_limit_is_independent_of_notifications_and_work
    def test_total_limit_is_independent_of_notifications_and_work(self) -> None:
        clock = RunClocks(10, .6, {"totalSeconds": 2, "idleSeconds": 0})
        clock.acknowledge(10.2)
        self.assertIsNone(clock.check(11.99, 11.99, True))
        error = clock.check(12, 12, True)
        assert error is not None
        self.assertEqual(error.result["detail"], {"basis": "fields", "limit": "total"})
# TEST-TIER-END tests/test_run_clocks.py::RunClockTests.test_total_limit_is_independent_of_notifications_and_work
