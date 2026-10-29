"""Commented mid-tier selections; see MID_TIER.md before restoring a case."""

# Restore the needed imports and class header only for an explicit testing task.
# import test_tool_runs as _support
# from test_tool_runs import (
#     Fixture,
#     ToolRuns,
# )


# class ToolRuns(_support.ToolRuns):
# TEST-TIER-DISABLED-BEGIN tests/test_tool_runs.py::ToolRuns.test_resume_forwards_changed_owner_mcp_in_memory_without_polluting_saved_state
#     async def test_resume_forwards_changed_owner_mcp_in_memory_without_polluting_saved_state(self) -> None:
#         owner = self.home / ".codex"
#         owner.mkdir()
#         skill = self.home / ".agents/skills/fixture-skill/SKILL.md"
#         skill.parent.mkdir(parents=True)
#         skill.write_text("---\nname: fixture-skill\ndescription: A sentinel skill\n---\nSkill sentinel\n")
#         history: list[Json] = []
#         path = self.home / "request.json"
#         secrets: list[str] = []
#         for index in range(3):
#             secret = f"fixture-resumed-owner-secret-{index}-private-12345"
#             secrets.append(secret)
#             config = (
#                 'model = "owner-model-sentinel"\n'
#                 "[mcp_servers.fixture]\n"
#                 'command = "fixture-server"\n'
#                 f'args = ["version-{index}"]\n'
#                 "[mcp_servers.fixture.env]\n"
#                 f'TOKEN = "{secret}"\n'
#             )
#             (owner / "config.toml").write_text(config)
#             metadata = (owner / "config.toml").stat()
#             self.scenario("C14 plain")
#             input_: Object = {"role": "user", "text": f"owner-run-{index}"}
#             path.write_text(
#                 dumps(
#                     {
#                         "subscriptionId": "chatgpt",
#                         "runId": "owner-mcp-resume",
#                         "chatSessionId": "owner-mcp-chat",
#                         "workingDirectory": str(self.home),
#                         "tools": "all",
#                         "input": input_,
#                         "history": history,
#                     }
#                 )
#             )
#             code, output, error = await self.invoke(["run", "--request", str(path)])
#             self.assertEqual((code, error), (0, b""), output)
#             events = [object_value(loads(line)) for line in output.decode().splitlines()]
#             self.assertEqual(events[0]["continuity"], "fresh" if index == 0 else "resumed")
#             self.assertEqual(events[-1]["outcome"], "completed")
#             history.extend(
#                 [
#                     {"type": "message", **input_},
#                     *(
#                         {"type": "message", "role": "assistant", "text": event["text"]}
#                         for event in events
#                         if event["type"] == "text" and "parentCallId" not in event
#                     ),
#                 ]
#             )
#             seen = next(record for record in self.records() if record.get("stage") == "input")
#             checks = object_value(seen["checks"])
#             self.assertTrue(checks["ownerMcpCorrect"])
#             self.assertFalse(checks["ownerMcpOmitted"])
#             self.assertEqual(checks["resumed"], index > 0)
#             self.assertEqual((owner / "config.toml").read_text(), config)
#             self.assertEqual((owner / "config.toml").stat().st_mtime_ns, metadata.st_mtime_ns)
#             self.assertEqual((owner / "config.toml").stat().st_mode, metadata.st_mode)
#             for private in secrets:
#                 self.assertNotIn(private.encode(), output + error + self.log.read_bytes())
#                 for state_file in self.state.rglob("*"):
#                     if state_file.is_file():
#                         self.assertNotIn(private.encode(), state_file.read_bytes(), str(state_file))
# TEST-TIER-DISABLED-END tests/test_tool_runs.py::ToolRuns.test_resume_forwards_changed_owner_mcp_in_memory_without_polluting_saved_state

# TEST-TIER-DISABLED-BEGIN tests/test_tool_runs.py::ToolRuns.test_late_noncommand_child_tool_closes_after_completed_turns_and_background_work
#     async def test_late_noncommand_child_tool_closes_after_completed_turns_and_background_work(self) -> None:
#         self.scenario("C35 child-late-tool")
#         code, output, error = await self.invoke(
#             ["run", "--subscription", "chatgpt", "--tools", "all", "--cwd", str(self.home), "answer"]
#         )
#         self.assertEqual((code, error), (0, b""), output)
#         events = [object_value(loads(line)) for line in output.decode().splitlines()]
#         late = [event for event in events if event.get("callId") == "child-late-mcp"]
#         self.assertEqual([event["type"] for event in late], ["tool_started", "tool_finished"])
#         self.assertTrue(late[-1]["ok"])
#         self.assertEqual(late[-1]["result"], {"late": True})
#         self.assertEqual([event["parentCallId"] for event in late], ["agent", "agent"])
#         ended = next(
#             event for event in events if event.get("callId") == "background" and event["type"] == "tool_finished"
#         )
#         self.assertLess(events.index(ended), events.index(late[-1]))
#         self.assertEqual(events[-1]["outcome"], "completed")
#         self.assertEqual(events[-1]["unfinishedCalls"], [])
#         self.assertEqual(
#             [
#                 record["stage"]
#                 for record in self.records()
#                 if record.get("stage") in ("main-ended", "child-ended", "background-ended", "child-tool-ended")
#             ],
#             ["main-ended", "child-ended", "background-ended", "child-tool-ended"],
#         )
# TEST-TIER-DISABLED-END tests/test_tool_runs.py::ToolRuns.test_late_noncommand_child_tool_closes_after_completed_turns_and_background_work


# Original deferred imports (restore at the required scope, never blindly at the tail).
# TEST-TIER-IMPORTS-BEGIN tests/test_tool_runs.py:3
# from arbol_codex_driver.json_types import Json, Object, dumps, loads, object_value
# TEST-TIER-IMPORTS-END tests/test_tool_runs.py:3

raise RuntimeError("Mid-tier tests require an explicitly requested testing task; see MID_TIER.md.")
