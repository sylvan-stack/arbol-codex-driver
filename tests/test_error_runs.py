"""Whole-process error and clock races through the credential-free vendor."""


from test_lifecycle import Fixture

from arbol_codex_driver.json_types import Object, loads, object_value


class ErrorRuns(Fixture):
# TEST-TIER-DISABLED-BEGIN tests/test_error_runs.py::ErrorRuns.test_rejected_retry_before_turn_start_reply_interrupts_accepted_turn
#     async def test_rejected_retry_before_turn_start_reply_interrupts_accepted_turn(self) -> None:
#         self.scenario("C28 auth-start-race")
#         running = cast(Running, await self.start("auth-race"))
#         accepted = await self.until_record("accepted-turn")
#         self.assertEqual(object_value(accepted["checks"])["turnId"], "fixture-turn")
#         self.assertEqual(await running.done(), (1, b""))
#         final = self.final(running.events, "failed")
#         self.assertEqual(object_value(final["error"])["code"], "credential_rejected")
#         self.assertEqual(sum(event["type"] == "notice" and event.get("code") == "retrying" for event in running.events), 1)
#         interrupts = [record for record in self.records() if record.get("stage") == "interrupt"]
#         self.assertEqual(len(interrupts), 1)
#         self.assertEqual(object_value(interrupts[0]["request"])["params"], {"threadId": "fixture-thread", "turnId": "fixture-turn"})
#         self.assertFalse(any(record.get("stage") == "second-retry" for record in self.records()))
#         self.assertFalse(any(record.get("stage") == "turn-start-reply" for record in self.records()))
#         self.assertFalse((self.state / "tmp/auth-race").exists())
#         self.assertFalse((self.state / "runs/auth-race.json").exists())
#         self.assert_attention(final)
# TEST-TIER-DISABLED-END tests/test_error_runs.py::ErrorRuns.test_rejected_retry_before_turn_start_reply_interrupts_accepted_turn

# TEST-TIER-DISABLED-BEGIN tests/test_error_runs.py::ErrorRuns.test_rejected_unknown_child_retry_is_replayed_after_spawn_discovery
#     async def test_rejected_unknown_child_retry_is_replayed_after_spawn_discovery(self) -> None:
#         self.scenario("C28 auth-child-replay")
#         running = cast(Running, await self.start("child-auth"))
#         self.assertEqual(await running.done(), (1, b""))
#         final = self.final(running.events, "failed")
#         self.assertEqual(object_value(final["error"])["code"], "credential_rejected")
#         retry = [event for event in running.events if event["type"] == "notice" and event.get("code") == "retrying"]
#         self.assertEqual(len(retry), 1)
#         self.assertEqual(retry[0]["parentCallId"], "fixture-auth-spawn")
#         interrupts = [object_value(object_value(record["request"])["params"])["threadId"] for record in self.records() if record.get("stage") == "interrupt"]
#         self.assertCountEqual(interrupts, ["fixture-thread", "fixture-subagent-thread"])
#         self.assertFalse((self.state / "tmp/child-auth").exists())
#         self.assertFalse((self.state / "runs/child-auth.json").exists())
#         self.assert_attention(final)
# TEST-TIER-DISABLED-END tests/test_error_runs.py::ErrorRuns.test_rejected_unknown_child_retry_is_replayed_after_spawn_discovery

    def assert_attention(self, final: Object) -> None:
        subscription = object_value(loads((self.state / "subscriptions/chatgpt/record.json").read_text()))
        self.assertEqual(subscription["state"], "needs_attention")
        self.assertEqual(subscription["problem"], final["error"])

# TEST-TIER-DISABLED-BEGIN tests/test_error_runs.py::ErrorRuns.test_total_limit_cleans_vendor_and_bounds_wait_for_blocked_output
#     async def test_total_limit_cleans_vendor_and_bounds_wait_for_blocked_output(self) -> None:
#         # Scale 5 gives the tool a stop grace of 0.4 seconds to see the interrupt, so that a busy machine cannot
#         # use it up first; the bounds follow from the scale and equal the former ones at scale 10.
#         scale = 5
#         self.env["ARBOL_TEST_TIME_SCALE"] = str(scale)
#         grace, stop = 2 / scale, 15 / scale
#         self.scenario("C29 blocked-output")
#         request = self.home / "clock-request.json"
#         request.write_text(dumps({
#             "runId": "blocked-limit", "subscriptionId": "chatgpt", "tools": "all", "history": [],
#             "workingDirectory": str(self.home), "input": {"role": "user", "text": "answer"},
#             "limits": {"idleSeconds": 0, "totalSeconds": 0.3},
#         }))
#         child = cast(asyncio.subprocess.Process, await self.start("blocked-limit", control=False, extra=["--request", str(request)], read=False))
#         checks = object_value((await self.until_record("input"))["checks"])
#         owner = await process_owner(cast(int, checks["toolPid"]))
#         self.assertIsNotNone(owner)
#         assert owner is not None
#         self.owners.append(owner)
#         started = time.monotonic()
#         async with asyncio.timeout(0.3 + grace + 1.5):
#             while await owner_alive(owner):
#                 await asyncio.sleep(0.01)
#         async with asyncio.timeout(stop + 1.5):
#             while child.returncode is None:
#                 await asyncio.sleep(0.01)
#         self.assertEqual(child.returncode, 1)
#         self.assertLess(time.monotonic() - started, 0.3 + stop + 1.0)
#         self.assertTrue(any(record.get("stage") == "interrupt" for record in self.records()))
#         assert child.stdout is not None and child.stderr is not None
#         cast(ReaderTransport, child.stdout)._transport.close()
#         self.assertEqual(await child.stderr.read(), b"")
#         await self.cleaned("blocked-limit", [owner])
# TEST-TIER-DISABLED-END tests/test_error_runs.py::ErrorRuns.test_total_limit_cleans_vendor_and_bounds_wait_for_blocked_output

# Archived complete imports; restore needed names in their original scope, not at this file tail.
# TEST-TIER-IMPORTS-BEGIN tests/test_error_runs.py:3
# import asyncio
# TEST-TIER-IMPORTS-END tests/test_error_runs.py:3
# TEST-TIER-IMPORTS-BEGIN tests/test_error_runs.py:4
# import time
# TEST-TIER-IMPORTS-END tests/test_error_runs.py:4
# TEST-TIER-IMPORTS-BEGIN tests/test_error_runs.py:5
# from typing import cast
# TEST-TIER-IMPORTS-END tests/test_error_runs.py:5
# TEST-TIER-IMPORTS-BEGIN tests/test_error_runs.py:7
# from test_lifecycle import Fixture, ReaderTransport, Running
# TEST-TIER-IMPORTS-END tests/test_error_runs.py:7
# TEST-TIER-IMPORTS-BEGIN tests/test_error_runs.py:9
# from arbol_codex_driver.json_types import Object, dumps, loads, object_value
# TEST-TIER-IMPORTS-END tests/test_error_runs.py:9
# TEST-TIER-IMPORTS-BEGIN tests/test_error_runs.py:10
# from arbol_codex_driver.state import owner_alive, process_owner
# TEST-TIER-IMPORTS-END tests/test_error_runs.py:10
