
# LOW TIER — DO NOT ENABLE OR RECREATE
# Historical examples only. Read before adding related tests; never execute.
# LOW-TIER-BEGIN: tests/mid/test_mid_run_clocks.py::RunClockTests.test_start_budget_spans_individual_startup_requests
# Reason: Supplies literal timestamps to the local deadline predicates; it does not establish real startup/idle/total enforcement. Real conformance/lifecycle deadlines remain the integration evidence; the arithmetic is directly visible in the implementation. Case reviewed: Start budget spans individual startup requests.
# Source: arbol-codex-driver@0c596c5960c34039bd48d05df9b66b4ea9f31680:tests/mid/test_mid_run_clocks.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     def test_start_budget_spans_individual_startup_requests(self) -> None:
#         clock = RunClocks(10, 60, None)
#         self.assertIsNone(clock.check(69.9, 69, False))
#         error = clock.check(70, 69, False)
#         assert error is not None
#         self.assertEqual(error.result["code"], "limit_reached")
#         self.assertEqual(error.result["detail"], {"basis": "fields", "limit": "start"})
#         clock.acknowledge(70)
#         self.assertIsNone(clock.check(71, 70, False))
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_run_clocks.py::RunClockTests.test_any_notification_resets_idle_and_zero_disables_it
# Reason: Supplies literal timestamps to the local deadline predicates; it does not establish real startup/idle/total enforcement. Real conformance/lifecycle deadlines remain the integration evidence; the arithmetic is directly visible in the implementation. Case reviewed: Any notification resets idle and zero disables it.
# Source: arbol-codex-driver@0c596c5960c34039bd48d05df9b66b4ea9f31680:tests/mid/test_mid_run_clocks.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     def test_any_notification_resets_idle_and_zero_disables_it(self) -> None:
#         clock = RunClocks(0, 60, {"idleSeconds": 3})
#         clock.acknowledge(1)
#         for at in (3, 5, 7):
#             self.assertIsNone(clock.check(at, at - 1, False))
#         error = clock.check(9, 6, False)
#         assert error is not None
#         self.assertEqual(error.result["detail"], {"basis": "fields", "limit": "idle"})
#         off = RunClocks(0, 60, {"idleSeconds": 0})
#         off.acknowledge(1)
#         self.assertIsNone(off.check(100000, 1, False))
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_run_clocks.py::RunClockTests.test_running_call_and_background_work_preserve_idle_budget
# Reason: Supplies literal timestamps to the local deadline predicates; it does not establish real startup/idle/total enforcement. Real conformance/lifecycle deadlines remain the integration evidence; the arithmetic is directly visible in the implementation. Case reviewed: Running call and background work preserve idle budget.
# Source: arbol-codex-driver@0c596c5960c34039bd48d05df9b66b4ea9f31680:tests/mid/test_mid_run_clocks.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     def test_running_call_and_background_work_preserve_idle_budget(self) -> None:
#         clock = RunClocks(0, 60, {"idleSeconds": 3})
#         clock.acknowledge(1)
#         self.assertIsNone(clock.check(2, 1, True))
#         self.assertIsNone(clock.check(200, 1, True))
#         self.assertIsNone(clock.check(201, 1, False))
#         self.assertIsNone(clock.check(202, 1, False))
#         self.assertIsNotNone(clock.check(203, 1, False))
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_run_clocks.py::RunClockTests.test_total_limit_is_independent_of_notifications_and_work
# Reason: Supplies literal timestamps to the local deadline predicates; it does not establish real startup/idle/total enforcement. Real conformance/lifecycle deadlines remain the integration evidence; the arithmetic is directly visible in the implementation. Case reviewed: Total limit is independent of notifications and work.
# Source: arbol-codex-driver@0c596c5960c34039bd48d05df9b66b4ea9f31680:tests/mid/test_mid_run_clocks.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     def test_total_limit_is_independent_of_notifications_and_work(self) -> None:
#         clock = RunClocks(10, .6, {"totalSeconds": 2, "idleSeconds": 0})
#         clock.acknowledge(10.2)
#         self.assertIsNone(clock.check(11.99, 11.99, True))
#         error = clock.check(12, 12, True)
#         assert error is not None
#         self.assertEqual(error.result["detail"], {"basis": "fields", "limit": "total"})
# LOW-TIER-SOURCE-END
# LOW-TIER-END
