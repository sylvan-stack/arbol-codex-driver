"""Mid-tier selections. Write or run only in an explicitly requested testing task."""
from __future__ import annotations

import test_dev as _support
from test_dev import (AsyncMock ,Cancellation ,Coroutine ,Failure ,Path ,asyncio ,command ,loads ,now ,object_value ,patch ,read_json ,stop_child ,sys ,write_json)


class DevChecks(_support.DevChecks):
# TEST-TIER-BEGIN tests/test_dev.py::DevChecks.test_cli_build_sends_exactly_one_no_tools_ready_request_and_reports_spend
    async def test_cli_build_sends_exactly_one_no_tools_ready_request_and_reports_spend(self) -> None:
        code, output, error = await self.invoke(["dev", "build-check"])
        self.assertEqual((code, error), (0, b""), output)
        result = object_value(loads(output.decode()))
        self.assertEqual((result["outcome"], result["turnsAttempted"], result["inferenceRequests"]), ("passed", 1, 1))
        self.assertEqual(result["subscriptionId"], "test-chatgpt")
        self.assertTrue(object_value(result["tokenUsage"]))
        self.assertIn("usageChange", result)
        self.assertEqual(read_json(Path(str(result["reportPath"]))), result)
        self.assertIn("runtime", object_value(result["provenance"]))
        requests = [record for record in self.records() if record.get("stage") == "input"]
        self.assertEqual(len(requests), 1)
        checks = object_value(requests[0]["checks"])
        params = object_value(object_value(checks["input"])["params"])
        self.assertEqual(params["approvalPolicy"], "never")
        self.assertEqual(params["sandboxPolicy"], {"type": "readOnly", "networkAccess": False})
        self.assertFalse(any(path.name.startswith("build-check-") for path in (self.state / "tmp").iterdir()))
        self.assertNotIn(b"fixture@example.invalid", output)
# TEST-TIER-END tests/test_dev.py::DevChecks.test_cli_build_sends_exactly_one_no_tools_ready_request_and_reports_spend

# TEST-TIER-BEGIN tests/test_dev.py::DevChecks.test_probe_no_prompt_shapes_owner_isolation_and_private_cleanup
    async def test_probe_no_prompt_shapes_owner_isolation_and_private_cleanup(self) -> None:
        owner = self.home / ".codex"
        owner.mkdir()
        sentinel = owner / "auth.json"
        sentinel.write_text("private-owner-login-sentinel")
        metadata = sentinel.stat()
        self.env.update(OPENAI_API_KEY="inherited-secret", CODEX_HOME=str(owner), CLAUDECODE="1")
        code, output, error = await self.invoke(["dev", "probe"])
        self.assertEqual((code, error), (0, b""), output)
        result = object_value(loads(output.decode()))
        self.assertEqual((result["inferenceRequests"], result["outcome"]), (0, "passed"))
        self.assertEqual(sentinel.read_text(), "private-owner-login-sentinel")
        self.assertEqual(sentinel.stat().st_mtime_ns, metadata.st_mtime_ns)
        self.assertFalse(any(path.name.startswith("probe-") for path in (self.state / "tmp").iterdir()))
        for private in ("private-owner-login-sentinel", "fixture@example.invalid", "fixture-secret", "gpt-6.1-sol"):
            self.assertNotIn(private.encode(), output)
        records = self.records()
        self.assertFalse(any(record.get("stage") == "input" for record in records))
        for record in records:
            environment = record.get("environment", [])
            assert isinstance(environment, list)
            self.assertNotIn("OPENAI_API_KEY", environment)
            self.assertNotIn("CLAUDECODE", environment)
        self.assertEqual(read_json(Path(str(result["reportPath"]))), result)
# TEST-TIER-END tests/test_dev.py::DevChecks.test_probe_no_prompt_shapes_owner_isolation_and_private_cleanup

# TEST-TIER-BEGIN tests/test_dev.py::DevChecks.test_missing_unsigned_and_cached_exhaustion_refuse_before_tool_start
    async def test_missing_unsigned_and_cached_exhaustion_refuse_before_tool_start(self) -> None:
        path = self.state / "subscriptions/test-chatgpt/record.json"
        original = object_value(read_json(path))
        for kind in ("missing", "unsigned", "exhausted"):
            self.scenario("C32 plain")
            if kind == "missing":
                path.unlink()
            else:
                record = {**original, "state": "signed_out" if kind == "unsigned" else "signed_in"}
                if kind == "exhausted":
                    record["lastUsage"] = {
                        "outcome": "ok",
                        "fetchedAt": now(),
                        "windows": [{"usedPercent": 100}],
                        "extra": {"credits": {"hasCredits": True}},
                    }
                write_json(path, record)
            for mode in ("build-check", "live-check"):
                code, output, error = await self.invoke(["dev", mode])
                self.assertEqual((code, error), (1, b""), output)
                result = object_value(loads(output.decode()))
                self.assertEqual(
                    object_value(result["error"])["code"],
                    "not_found" if kind == "missing" else "not_signed_in" if kind == "unsigned" else "rate_limited",
                )
                self.assertEqual((result["turnsAttempted"], result["inferenceRequests"]), (0, 0))
                self.assertFalse(self.log.exists())
            write_json(path, original)
# TEST-TIER-END tests/test_dev.py::DevChecks.test_missing_unsigned_and_cached_exhaustion_refuse_before_tool_start


# TEST-TIER-BEGIN tests/test_dev.py::DevChecks.test_process_identity_lookup_failure_still_ends_spawned_probe_child
    async def test_process_identity_lookup_failure_still_ends_spawned_probe_child(self) -> None:
        pid_file = self.home / "probe-child-pid"
        script = (
            "import os,time; from pathlib import Path; Path("
            + repr(str(pid_file))
            + ").write_text(str(os.getpid())); time.sleep(30)"
        )

        async def failed_lookup(pid: int) -> None:
            async with asyncio.timeout(2):
                while not pid_file.exists():
                    await asyncio.sleep(0.005)
            raise Failure("internal", "Synthetic process lookup failure.")

        with patch("arbol_codex_driver.dev_support.process_owner", failed_lookup):
            with self.assertRaises(Failure):
                await command(sys.executable, ["-I", "-c", script], self.env, self.home, Cancellation())
        from arbol_codex_driver.state import process_owner

        self.assertIsNone(await process_owner(int(pid_file.read_text())))
# TEST-TIER-END tests/test_dev.py::DevChecks.test_process_identity_lookup_failure_still_ends_spawned_probe_child

# TEST-TIER-BEGIN tests/test_dev.py::DevChecks.test_forced_driver_cleanup_identity_failure_still_reaps_child
    async def test_forced_driver_cleanup_identity_failure_still_reaps_child(self) -> None:
        ready = self.home / "ignoring-child-ready"
        script = (
            "import signal,time; from pathlib import Path; signal.signal(signal.SIGTERM,signal.SIG_IGN); Path("
            + repr(str(ready))
            + ").touch(); time.sleep(30)"
        )
        child = await asyncio.create_subprocess_exec(
            sys.executable,
            "-I",
            "-c",
            script,
            start_new_session=True,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        self.children.append(child)
        async with asyncio.timeout(2):
            while not ready.exists():
                await asyncio.sleep(0.005)
        real_wait = asyncio.wait_for

        async def fast_wait(work: Coroutine[object, object, object], seconds: float) -> object:
            if seconds == 20:
                work.close()
                raise TimeoutError
            return await real_wait(work, seconds)

        with (
            patch("arbol_codex_driver.dev_support.asyncio.wait_for", fast_wait),
            patch(
                "arbol_codex_driver.dev_support.process_owner",
                AsyncMock(side_effect=Failure("internal", "Synthetic identity failure.")),
            ),
        ):
            with self.assertRaises(Failure) as raised:
                await stop_child(child)
        self.assertEqual(raised.exception.result["code"], "internal")
        self.assertIsNotNone(child.returncode)
# TEST-TIER-END tests/test_dev.py::DevChecks.test_forced_driver_cleanup_identity_failure_still_reaps_child

# LOW TIER — DO NOT ENABLE OR RECREATE
# Historical examples only. Read before adding related tests; never execute.
# LOW-TIER-BEGIN: tests/mid/test_mid_dev.py::DevShapes.test_probe_shapes_keep_only_bounded_protocol_enums_and_no_values
# Reason: Checks diagnostic helper output or feeds canned success/error events into the testing harness. Retained actual CLI prerequisite/isolation/spend and child-cleanup checks cover distinct operational boundaries; these simulated reporting variants do not justify separate tests. Case reviewed: Probe shapes keep only bounded protocol enums and no values.
# Source: arbol-codex-driver@0c596c5960c34039bd48d05df9b66b4ea9f31680:tests/mid/test_mid_dev.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     def test_probe_shapes_keep_only_bounded_protocol_enums_and_no_values(self) -> None:
#         shaped = probe_shape(
#             {
#                 "account": {"type": "chatgpt", "email": "owner-private@example.invalid", "planType": "private-plan"},
#                 "userCode": "SECRET-CODE",
#                 "models": [{"id": "gpt-secret", "defaultReasoningEffort": "low"}],
#                 "null": None,
#                 "truth": True,
#                 "usage": 47.5,
#                 "status": "private-status",
#             }
#         )
#         self.assertEqual(
#             shaped,
#             {
#                 "account": {"type": "chatgpt", "email": "string", "planType": "string"},
#                 "userCode": "string",
#                 "models": [{"id": "string", "defaultReasoningEffort": "low"}],
#                 "null": None,
#                 "truth": "boolean",
#                 "usage": "number",
#                 "status": "string",
#             },
#         )
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_dev.py::DevShapes.test_exhaustion_never_uses_credits_and_covers_model_specific_windows
# Reason: Checks diagnostic helper output or feeds canned success/error events into the testing harness. Retained actual CLI prerequisite/isolation/spend and child-cleanup checks cover distinct operational boundaries; these simulated reporting variants do not justify separate tests. Case reviewed: Exhaustion never uses credits and covers model specific windows.
# Source: arbol-codex-driver@0c596c5960c34039bd48d05df9b66b4ea9f31680:tests/mid/test_mid_dev.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     def test_exhaustion_never_uses_credits_and_covers_model_specific_windows(self) -> None:
#         for report in (
#             {"windows": [{"kind": "weekly", "usedPercent": 100}], "extra": {"credits": {"hasCredits": True}}},
#             {"windows": [{"limitReached": True}]},
#             {"windows": [], "extra": {"ordinaryUsageAllowed": False, "credits": {"hasCredits": True}}},
#             {"windows": [], "extra": {"spendControlReached": True}},
#             {"windows": [], "extra": {"rateLimitsByLimitId": {"a": {"secondary": {"usedPercent": 100}}}}},
#         ):
#             with self.subTest(report=report), self.assertRaises(Failure) as raised:
#                 refuse_exhausted(cast(Object, report))
#             self.assertEqual(raised.exception.result["code"], "rate_limited")
#         refuse_exhausted({"windows": [{"usedPercent": 99.9}], "extra": {"ordinaryUsageAllowed": True}})
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_dev.py::DevShapes.test_model_choice_uses_live_catalog_and_lowest_supported_effort
# Reason: Checks diagnostic helper output or feeds canned success/error events into the testing harness. Retained actual CLI prerequisite/isolation/spend and child-cleanup checks cover distinct operational boundaries; these simulated reporting variants do not justify separate tests. Case reviewed: Model choice uses live catalog and lowest supported effort.
# Source: arbol-codex-driver@0c596c5960c34039bd48d05df9b66b4ea9f31680:tests/mid/test_mid_dev.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     def test_model_choice_uses_live_catalog_and_lowest_supported_effort(self) -> None:
#         catalog: Object = {
#             "source": "tool",
#             "models": [
#                 {"id": "large", "isDefault": True, "efforts": ["high"]},
#                 {"id": "gpt-5.6-luna", "efforts": ["medium", "low", "high"]},
#             ],
#         }
#         self.assertEqual(select_model(catalog), ("gpt-5.6-luna", "low"))
#         self.assertEqual(
#             select_model({"source": "tool", "models": [{"id": "future-luna", "efforts": ["none", "low"]}]}),
#             ("future-luna", "none"),
#         )
#         with self.assertRaises(Failure):
#             select_model({"source": "builtin", "models": [{"id": "gpt-5.6-luna"}]})
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_dev.py::DevShapes.test_sparse_usage_change_does_not_invent_percentages
# Reason: Checks diagnostic helper output or feeds canned success/error events into the testing harness. Retained actual CLI prerequisite/isolation/spend and child-cleanup checks cover distinct operational boundaries; these simulated reporting variants do not justify separate tests. Case reviewed: Sparse usage change does not invent percentages.
# Source: arbol-codex-driver@0c596c5960c34039bd48d05df9b66b4ea9f31680:tests/mid/test_mid_dev.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     def test_sparse_usage_change_does_not_invent_percentages(self) -> None:
#         self.assertEqual(
#             usage_change(
#                 {"windows": [{"kind": "weekly", "label": "Weekly", "usedPercent": 4}]},
#                 {
#                     "windows": [
#                         {"kind": "weekly", "label": "Weekly", "usedPercent": 7},
#                         {"kind": "session", "label": "Session"},
#                     ]
#                 },
#             ),
#             [
#                 {"kind": "weekly", "label": "Weekly", "beforePercent": 4, "afterPercent": 7, "changePercent": 3},
#                 {"kind": "session", "label": "Session"},
#             ],
#         )
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_dev.py::DevChecks.test_refreshed_exhaustion_or_unavailable_usage_never_starts_run
# Reason: Checks diagnostic helper output or feeds canned success/error events into the testing harness. Retained actual CLI prerequisite/isolation/spend and child-cleanup checks cover distinct operational boundaries; these simulated reporting variants do not justify separate tests. Case reviewed: Refreshed exhaustion or unavailable usage never starts run.
# Source: arbol-codex-driver@0c596c5960c34039bd48d05df9b66b4ea9f31680:tests/mid/test_mid_dev.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_refreshed_exhaustion_or_unavailable_usage_never_starts_run(self) -> None:
#         for usage in ({"outcome": "ok", "windows": [{"usedPercent": 100}]}, {"outcome": "unavailable", "windows": []}):
#             with (
#                 patch.object(self.subscriptions, "usage", AsyncMock(return_value=usage)),
#                 patch("arbol_codex_driver.dev.execute_run", AsyncMock()) as execution,
#             ):
#                 with self.assertRaises(Failure):
#                     await check_account(self.subscriptions)
#                 code, report = await live_check(True, self.subscriptions, self.env, Cancellation())
#                 self.assertEqual(code, 1)
#                 self.assertEqual(report["turnsAttempted"], 0)
#                 execution.assert_not_awaited()
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_dev.py::DevChecks.test_live_is_explicit_five_turns_and_build_has_only_ready
# Reason: Checks diagnostic helper output or feeds canned success/error events into the testing harness. Retained actual CLI prerequisite/isolation/spend and child-cleanup checks cover distinct operational boundaries; these simulated reporting variants do not justify separate tests. Case reviewed: Live is explicit five turns and build has only ready.
# Source: arbol-codex-driver@0c596c5960c34039bd48d05df9b66b4ea9f31680:tests/mid/test_mid_dev.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_live_is_explicit_five_turns_and_build_has_only_ready(self) -> None:
#         requests: list[Object] = []
#
#         async def fake_run(
#             subscriptions: Subscriptions,
#             env: dict[str, str],
#             directory: Path,
#             request: Object,
#             cancellation: Cancellation,
#             stop: bool = False,
#         ) -> tuple[int, list[Object]]:
#             requests.append(request)
#             input_ = str(object_value(request["input"])["text"])
#             answer = "willow" if input_.startswith("What word") else "ready"
#             events: list[Object] = [
#                 {"type": "started", "continuity": "resumed" if request.get("history") else "fresh"},
#                 {"type": "text", "text": answer},
#             ]
#             if request["tools"] == "all":
#                 events.extend(
#                     [
#                         {"type": "tool_started", "callId": "call", "name": "shell"},
#                         {"type": "tool_finished", "callId": "call", "ok": True, "parentCallId": "agent"},
#                         {"type": "tool_started", "callId": "agent", "name": "spawnAgent"},
#                         {"type": "text", "text": "ARBOL_CHILD", "parentCallId": "agent"},
#                         {"type": "usage", "usage": {"inputTokens": 4, "outputTokens": 1}, "parentCallId": "agent"},
#                         {
#                             "type": "tool_started",
#                             "callId": "background",
#                             "name": "shell",
#                             "input": {"command": "sleep 2; printf ARBOL_BACKGROUND"},
#                         },
#                         {
#                             "type": "tool_finished",
#                             "callId": "background",
#                             "ok": True,
#                             "result": {"output": "ARBOL_BACKGROUND"},
#                         },
#                     ]
#                 )
#             events.append(
#                 {
#                     "type": "finished",
#                     "outcome": "cancelled" if stop else "completed",
#                     "usage": {"inputTokens": 10, "outputTokens": 2},
#                 }
#             )
#             for i, event in enumerate(events, 1):
#                 event["seq"] = i
#             return 2 if stop else 0, events
#
#         with patch("arbol_codex_driver.dev.execute_run", fake_run):
#             code, report = await live_check(True, self.subscriptions, self.env, Cancellation())
#             self.assertEqual((code, report["turnsAttempted"], len(requests)), (0, 1, 1))
#             self.assertEqual(object_value(requests[0]["input"])["text"], READY)
#             self.assertEqual(requests[0]["tools"], "none")
#             self.assertNotIn("workingDirectory", requests[0])
#             requests.clear()
#             code, report = await live_check(False, self.subscriptions, self.env, Cancellation())
#             self.assertEqual((code, report["turnsAttempted"], report["inferenceRequests"], len(requests)), (0, 5, 5, 5))
#             self.assertEqual(report["tokenUsage"], {"inputTokens": 50, "outputTokens": 10})
#             self.assertEqual(report["childTokenUsage"], {"inputTokens": 8, "outputTokens": 2})
#             self.assertEqual(requests[2]["chatSessionId"], requests[3]["chatSessionId"])
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_dev.py::DevChecks.test_failed_run_retains_observed_starts_tokens_and_usage_change
# Reason: Checks diagnostic helper output or feeds canned success/error events into the testing harness. Retained actual CLI prerequisite/isolation/spend and child-cleanup checks cover distinct operational boundaries; these simulated reporting variants do not justify separate tests. Case reviewed: Failed run retains observed starts tokens and usage change.
# Source: arbol-codex-driver@0c596c5960c34039bd48d05df9b66b4ea9f31680:tests/mid/test_mid_dev.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_failed_run_retains_observed_starts_tokens_and_usage_change(self) -> None:
#         events: list[Object] = [
#             {"type": "started", "seq": 1},
#             {"type": "usage", "seq": 2, "usage": {"inputTokens": 21, "outputTokens": 3}},
#             {"type": "finished", "seq": 3, "outcome": "failed", "usage": {"inputTokens": 21, "outputTokens": 3}},
#         ]
#         with patch("arbol_codex_driver.dev.execute_run", AsyncMock(return_value=(1, events))):
#             code, report = await live_check(True, self.subscriptions, self.env, Cancellation())
#         self.assertEqual((code, report["turnsAttempted"], report["inferenceRequests"]), (1, 1, 1))
#         self.assertEqual(report["tokenUsage"], {"inputTokens": 21, "outputTokens": 3})
#         self.assertEqual(object_value(report["usageAfter"])["outcome"], "ok")
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_dev.py::DevChecks.test_cleanup_failure_preserves_completed_run_spending_evidence
# Reason: Checks diagnostic helper output or feeds canned success/error events into the testing harness. Retained actual CLI prerequisite/isolation/spend and child-cleanup checks cover distinct operational boundaries; these simulated reporting variants do not justify separate tests. Case reviewed: Cleanup failure preserves completed run spending evidence.
# Source: arbol-codex-driver@0c596c5960c34039bd48d05df9b66b4ea9f31680:tests/mid/test_mid_dev.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_cleanup_failure_preserves_completed_run_spending_evidence(self) -> None:
#         self.scenario("C13 plain")
#         cleanup = AsyncMock(side_effect=Failure("tool_failed", "Synthetic cleanup failure."))
#         with patch("arbol_codex_driver.dev.Runs.list", cleanup):
#             with self.assertRaises(Failure) as raised:
#                 await execute_run(
#                     self.subscriptions,
#                     self.env,
#                     self.home,
#                     {
#                         "subscriptionId": "test-chatgpt",
#                         "tools": "none",
#                         "input": {"role": "user", "text": READY},
#                         "history": [],
#                     },
#                     Cancellation(),
#                 )
#         events = raised.exception.result.get("devEvents", [])
#         self.assertIsInstance(events, list)
#         self.assertTrue(any(object_value(event).get("type") == "started" for event in cast(list[Json], events)))
#         self.assertTrue(any(object_value(event).get("type") == "usage" for event in cast(list[Json], events)))
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_dev.py::DevChecks.test_partial_failure_marks_possible_missing_spend_and_preserves_observed_usage
# Reason: Checks diagnostic helper output or feeds canned success/error events into the testing harness. Retained actual CLI prerequisite/isolation/spend and child-cleanup checks cover distinct operational boundaries; these simulated reporting variants do not justify separate tests. Case reviewed: Partial failure marks possible missing spend and preserves observed usage.
# Source: arbol-codex-driver@0c596c5960c34039bd48d05df9b66b4ea9f31680:tests/mid/test_mid_dev.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_partial_failure_marks_possible_missing_spend_and_preserves_observed_usage(self) -> None:
#         failure = Failure("tool_failed", "Synthetic stream loss.")
#         failure.result["devEvents"] = [
#             {"type": "started", "seq": 1},
#             {"type": "usage", "seq": 2, "usage": {"inputTokens": 13, "outputTokens": 2}},
#         ]
#         with patch("arbol_codex_driver.dev.execute_run", AsyncMock(side_effect=failure)):
#             code, report = await live_check(True, self.subscriptions, self.env, Cancellation())
#         self.assertEqual((code, report["inferenceRequests"], report["turnsAttempted"]), (1, 1, 1))
#         self.assertTrue(report["spendMayBeIncomplete"])
#         self.assertEqual(report["tokenUsage"], {"inputTokens": 13, "outputTokens": 2})
#         self.assertNotIn("devEvents", object_value(report["error"]))
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_dev.py::DevChecks.test_child_cleanup_failure_retains_completed_run_evidence
# Reason: Checks diagnostic helper output or feeds canned success/error events into the testing harness. Retained actual CLI prerequisite/isolation/spend and child-cleanup checks cover distinct operational boundaries; these simulated reporting variants do not justify separate tests. Case reviewed: Child cleanup failure retains completed run evidence.
# Source: arbol-codex-driver@0c596c5960c34039bd48d05df9b66b4ea9f31680:tests/mid/test_mid_dev.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_child_cleanup_failure_retains_completed_run_evidence(self) -> None:
#         self.scenario("C13 plain")
#         with patch(
#             "arbol_codex_driver.dev.stop_child", AsyncMock(side_effect=Failure("tool_failed", "Synthetic cleanup."))
#         ):
#             with self.assertRaises(Failure) as raised:
#                 await execute_run(
#                     self.subscriptions,
#                     self.env,
#                     self.home,
#                     {
#                         "subscriptionId": "test-chatgpt",
#                         "tools": "none",
#                         "input": {"role": "user", "text": READY},
#                         "history": [],
#                     },
#                     Cancellation(),
#                 )
#         events = raised.exception.result.get("devEvents", [])
#         assert isinstance(events, list)
#         self.assertEqual(object_value(events[-1])["outcome"], "completed")
#         self.assertTrue(object_value(object_value(events[-1])["usage"]))
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_dev.py::DevChecks.test_probe_failure_is_typed_and_missing_schema_diagnostic_is_nonsecret
# Reason: Checks diagnostic helper output or feeds canned success/error events into the testing harness. Retained actual CLI prerequisite/isolation/spend and child-cleanup checks cover distinct operational boundaries; these simulated reporting variants do not justify separate tests. Case reviewed: Probe failure is typed and missing schema diagnostic is nonsecret.
# Source: arbol-codex-driver@0c596c5960c34039bd48d05df9b66b4ea9f31680:tests/mid/test_mid_dev.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_probe_failure_is_typed_and_missing_schema_diagnostic_is_nonsecret(self) -> None:
#         async def no_schema(*args: object, **kwargs: object) -> tuple[int, bytes]:
#             return 0, b""
#
#         with patch("arbol_codex_driver.dev.command", no_schema):
#             code, report = await probe(self.subscriptions, self.env, Cancellation())
#         self.assertEqual(code, 1)
#         self.assertEqual(object_value(report["error"])["code"], "tool_unsupported")
#         self.assertIn("ThreadStartParams", str(object_value(report["error"])["message"]))
#         self.assertEqual(report["inferenceRequests"], 0)
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_dev.py::DevChecks.test_probe_missing_and_old_tools_preserve_public_version_refusal_details
# Reason: Checks diagnostic helper output or feeds canned success/error events into the testing harness. Retained actual CLI prerequisite/isolation/spend and child-cleanup checks cover distinct operational boundaries; these simulated reporting variants do not justify separate tests. Case reviewed: Probe missing and old tools preserve public version refusal details.
# Source: arbol-codex-driver@0c596c5960c34039bd48d05df9b66b4ea9f31680:tests/mid/test_mid_dev.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_probe_missing_and_old_tools_preserve_public_version_refusal_details(self) -> None:
#         settings = self.home / ".arbol/arbol-codex-driver.json"
#         for missing in (True, False):
#             with self.subTest(missing=missing):
#                 self.scenario("C31 missing" if missing else "C31 old")
#                 (self.state / "tool.json").unlink(missing_ok=True)
#                 settings.write_text(dumps({"toolPath": str(self.tool / ("absent-codex" if missing else "codex"))}))
#                 code, output, stderr = await self.invoke(["dev", "probe"])
#                 self.assertEqual((code, stderr), (1, b""), output)
#                 report = object_value(loads(output.decode()))
#                 error = object_value(report["error"])
#                 self.assertEqual(error["code"], "tool_missing" if missing else "tool_unsupported")
#                 detail = object_value(error["detail"])
#                 self.assertEqual(detail["neededVersion"], OLDEST_SUPPORTED)
#                 self.assertEqual(detail["basis"], "fields")
#                 self.assertEqual(error["remedy"], "Install codex." if missing else "Update codex.")
#                 self.assertIn("codex", str(error["message"]))
#                 self.assertIn(OLDEST_SUPPORTED, str(error["message"]))
#                 if missing:
#                     self.assertFalse(self.log.exists())
#                 else:
#                     self.assertEqual(detail["toolVersion"], "0.159.1")
#                     self.assertIn("0.159.1", str(error["message"]))
#                     self.assertEqual([record["arguments"] for record in self.records()], [["--version"]])
#                 self.assertEqual(report["inferenceRequests"], 0)
#                 self.assertEqual(read_json(Path(str(report["reportPath"]))), report)
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_dev.py::DevChecks.test_probe_interrupt_transport_failure_does_not_count_as_vendor_refusal
# Reason: Checks diagnostic helper output or feeds canned success/error events into the testing harness. Retained actual CLI prerequisite/isolation/spend and child-cleanup checks cover distinct operational boundaries; these simulated reporting variants do not justify separate tests. Case reviewed: Probe interrupt transport failure does not count as vendor refusal.
# Source: arbol-codex-driver@0c596c5960c34039bd48d05df9b66b4ea9f31680:tests/mid/test_mid_dev.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_probe_interrupt_transport_failure_does_not_count_as_vendor_refusal(self) -> None:
#         original = AppServer.request
#
#         async def broken(
#             server: AppServer,
#             method: str,
#             params: Json,
#             *,
#             cancellation: Cancellation | None = None,
#             timeout: float | None = None,
#         ) -> Json:
#             if method == "turn/interrupt":
#                 raise Failure(
#                     "tool_failed",
#                     "Synthetic transport loss private-account-value.",
#                     {"detail": {"excerpt": "private-account-value"}},
#                 )
#             return await original(server, method, params, cancellation=cancellation, timeout=timeout)
#
#         with patch("arbol_codex_driver.dev.AppServer.request", broken):
#             code, report = await probe(self.subscriptions, self.env, Cancellation())
#         self.assertEqual(code, 1)
#         self.assertEqual(object_value(report["error"])["code"], "tool_failed")
#         self.assertNotIn("private-account-value", dumps(report))
#         self.assertNotIn("detail", object_value(report["error"]))
#         checks = report.get("checks", [])
#         assert isinstance(checks, list)
#         self.assertFalse(any(object_value(check).get("check") == "probe.stopping" for check in checks))
# LOW-TIER-SOURCE-END
# LOW-TIER-END
