"""Tool envelopes from the stable schema and retained vendor observations."""

import unittest
from typing import cast

from arbol_codex_driver.json_types import Json, Object
from arbol_codex_driver.run_events import RunEvents


class MapperTools(unittest.TestCase):
    def setUp(self) -> None:
        self.events: list[Object] = []
        self.mapper = RunEvents(
            "main", "main-turn", "model", lambda type_, data: self.events.append({"type": type_, **data})
        )

    def notify(self, method: str, data: Object, thread: str = "main", turn: str = "main-turn") -> None:
        self.mapper.consume(method, {"threadId": thread, "turnId": turn, **data})

    def item(self, method: str, item: Object, thread: str = "main", turn: str = "main-turn") -> None:
        self.notify(method, {"item": item}, thread, turn)

    def complete(self, thread: str = "main", turn: str = "main-turn", status: str = "completed") -> None:
        self.mapper.consume("turn/completed", {"threadId": thread, "turn": {"id": turn, "status": status}})

    def spawn(self, id_: str = "spawn", receivers: list[str] | None = None) -> None:
        item: Object = {
            "type": "collabAgentToolCall",
            "id": id_,
            "tool": "spawnAgent",
            "status": "inProgress",
            "receiverThreadIds": [],
        }
        self.item("item/started", item)
        self.item(
            "item/completed",
            {**item, "status": "completed", "receiverThreadIds": cast(list[Json], receivers or ["child"])},
        )

# TEST-TIER-DISABLED-BEGIN tests/test_tool_mapping.py::MapperTools.test_patch_kinds_and_vendor_failure_leave_run_completed
#     def test_patch_kinds_and_vendor_failure_leave_run_completed(self) -> None:
#         changes: list[Json] = [
#             {"path": "/work/new", "kind": {"type": "add"}, "diff": "new content\n"},
#             {
#                 "path": "/work/old",
#                 "kind": {"type": "update", "move_path": "/work/moved"},
#                 "diff": "@@ -1 +1 @@\n-old\n+new\n",
#             },
#             {"path": "/work/gone", "kind": {"type": "delete"}, "diff": "removed content\n"},
#         ]
#         for status in ("completed", "declined", "failed"):
#             started: Object = {"type": "fileChange", "id": status, "status": "inProgress", "changes": changes}
#             self.item("item/started", started)
#             self.assertEqual(self.events[-1]["name"], "apply_patch")
#             self.assertEqual(
#                 self.events[-1]["input"],
#                 [
#                     {"path": change["path"], "kind": change["kind"], "content": change["diff"]}
#                     for change in changes
#                     if isinstance(change, dict)
#                 ],
#             )
#             completed: Object = {**started, "status": status}
#             self.item("item/completed", completed)
#             self.assertEqual(self.events[-1]["result"], completed)
#             self.assertIs(self.events[-1]["ok"], status == "completed")
#             if status != "completed":
#                 self.assertEqual(self.events[-1]["error"], status)
#         self.complete()
#         self.assertEqual(self.mapper.outcome, "completed")
# TEST-TIER-DISABLED-END tests/test_tool_mapping.py::MapperTools.test_patch_kinds_and_vendor_failure_leave_run_completed

# TEST-TIER-DISABLED-BEGIN tests/test_tool_mapping.py::MapperTools.test_mcp_result_metadata_structured_content_and_error_reason
#     def test_mcp_result_metadata_structured_content_and_error_reason(self) -> None:
#         started: Object = {
#             "type": "mcpToolCall",
#             "id": "mcp",
#             "server": "fixture",
#             "tool": "lookup",
#             "arguments": {"key": "value"},
#             "status": "inProgress",
#             "result": None,
#             "error": None,
#         }
#         result: Object = {
#             "content": [{"type": "text", "text": "fixture result"}],
#             "structuredContent": {"rows": [{"count": 2}]},
#             "_meta": {"fixture/newField": [True, None]},
#         }
#         self.item("item/started", started)
#         self.assertEqual(
#             self.events[-1], {"type": "tool_started", "callId": "mcp", "name": "mcpToolCall", "input": started}
#         )
#         self.item("item/completed", {**started, "status": "completed", "result": result})
#         self.assertEqual(self.events[-1], {"type": "tool_finished", "callId": "mcp", "ok": True, "result": result})
#         refused: Object = {**started, "id": "refused"}
#         self.item("item/started", refused)
#         completed: Object = {**refused, "status": "failed", "error": {"message": "Server refused the request."}}
#         self.item("item/completed", completed)
#         self.assertEqual(self.events[-1]["error"], "Server refused the request.")
#         self.assertEqual(self.events[-1]["result"], completed)
#         self.assertIs(self.events[-1]["ok"], False)
#         self.complete()
#         self.assertEqual(self.mapper.outcome, "completed")
# TEST-TIER-DISABLED-END tests/test_tool_mapping.py::MapperTools.test_mcp_result_metadata_structured_content_and_error_reason

# TEST-TIER-DISABLED-BEGIN tests/test_tool_mapping.py::MapperTools.test_generic_tool_failures_preserve_reasons_and_success_false_is_failed
#     def test_generic_tool_failures_preserve_reasons_and_success_false_is_failed(self) -> None:
#         for index, field in enumerate(
#             (
#                 {"error": "String reason"},
#                 {"failure": {"message": "Structured reason"}},
#                 {"failure": "Failure reason"},
#                 {},
#             )
#         ):
#             started: Object = {
#                 "type": "dynamicToolCall",
#                 "id": str(index),
#                 "tool": "fixture",
#                 "arguments": {},
#                 "status": "inProgress",
#             }
#             self.item("item/started", started)
#             completed: Object = {
#                 **started,
#                 "status": "completed",
#                 "success": False,
#                 "contentItems": [{"type": "inputText", "text": "tool output"}],
#                 **cast(Object, field),
#             }
#             self.item("item/completed", completed)
#             self.assertIs(self.events[-1]["ok"], False)
#             self.assertEqual(
#                 self.events[-1]["error"], ("String reason", "Structured reason", "Failure reason", "failed")[index]
#             )
#             self.assertEqual(self.events[-1]["result"], completed)
#         self.item("item/started", {"type": "commandExecution", "id": "shell", "command": "fixture"})
#         self.item(
#             "item/completed",
#             {"type": "commandExecution", "id": "shell", "status": "declined", "error": "Command refused."},
#         )
#         self.assertEqual(self.events[-1]["error"], "Command refused.")
#         for status in ("declined", "failed"):
#             self.item("item/started", {"type": "commandExecution", "id": status, "command": "fixture"})
#             self.item(
#                 "item/completed",
#                 {
#                     "type": "commandExecution",
#                     "id": status,
#                     "status": status,
#                     "aggregatedOutput": "Codex refused this command.",
#                 },
#             )
#             self.assertEqual(self.events[-1]["error"], "Codex refused this command.")
# TEST-TIER-DISABLED-END tests/test_tool_mapping.py::MapperTools.test_generic_tool_failures_preserve_reasons_and_success_false_is_failed

# TEST-TIER-DISABLED-BEGIN tests/test_tool_mapping.py::MapperTools.test_web_results_are_opaque_and_large_mcp_results_are_utf8_bounded
#     def test_web_results_are_opaque_and_large_mcp_results_are_utf8_bounded(self) -> None:
#         started: Object = {"type": "webSearch", "id": "web", "query": "", "action": None, "results": None}
#         completed: Object = {
#             **started,
#             "query": "fixture query",
#             "action": {"type": "search", "queries": ["fixture query"]},
#             "results": [{"type": "future_result", "fixture": {"nested": [1, True, None]}}],
#         }
#         self.item("item/started", started)
#         self.item("item/completed", completed)
#         self.assertEqual(self.events[-1]["result"], completed)
#         self.assertEqual(self.events[0]["name"], "webSearch")
#         mcp: Object = {
#             "type": "mcpToolCall",
#             "id": "large",
#             "status": "inProgress",
#             "server": "fixture",
#             "tool": "large",
#             "arguments": {},
#         }
#         self.item("item/started", mcp)
#         self.item(
#             "item/completed", {**mcp, "status": "completed", "result": {"content": [{"text": "🌲" * RESULT_LIMIT}]}}
#         )
#         result = self.events[-1]
#         self.assertIs(result["truncated"], True)
#         self.assertLessEqual(len(utf8(str(result["result"]))), RESULT_LIMIT)
#         self.assertNotIn("�", str(result["result"]))
# TEST-TIER-DISABLED-END tests/test_tool_mapping.py::MapperTools.test_web_results_are_opaque_and_large_mcp_results_are_utf8_bounded

# TEST-TIER-DISABLED-BEGIN tests/test_tool_mapping.py::MapperTools.test_child_post_turn_output_notices_and_retry_keep_parent_attribution
#     def test_child_post_turn_output_notices_and_retry_keep_parent_attribution(self) -> None:
#         self.spawn()
#         self.item(
#             "item/started",
#             {"type": "commandExecution", "id": "background", "command": "sleep fixture"},
#             "child",
#             "child-turn",
#         )
#         self.complete("child", "child-turn")
#         self.complete()
#         self.assertTrue(self.mapper.waiting_for_work)
#         self.assertEqual(self.mapper.active_turns, [])
#         self.notify(
#             "item/commandExecution/outputDelta", {"itemId": "background", "delta": "late output"}, "child", "child-turn"
#         )
#         self.notify("error", {"willRetry": True, "error": {"message": "Retrying child."}}, "child", "child-turn")
#         self.mapper.consume("warning", {"threadId": "child", "message": "Child warning."})
#         self.mapper.consume(
#             "deprecationNotice", {"threadId": "child", "summary": "Child deprecation.", "details": "Details."}
#         )
#         self.mapper.consume(
#             "driver/notice", {"threadId": "child", "code": "unexpected_request", "message": "No client tool."}
#         )
#         self.item(
#             "item/completed",
#             {"type": "commandExecution", "id": "background", "status": "completed", "exitCode": 0},
#             "child",
#             "child-turn",
#         )
#         child_events = self.events[2:]
#         self.assertTrue(child_events)
#         self.assertTrue(all(event.get("parentCallId") == "spawn" for event in child_events))
#         self.assertIn(
#             {"type": "notice", "parentCallId": "spawn", "code": "unexpected_request", "message": "No client tool."},
#             child_events,
#         )
#         self.assertEqual(child_events[-1]["result"], {"output": "late output", "exitCode": 0})
#         self.assertFalse(self.mapper.waiting_for_work)
#         self.assertEqual(self.mapper.outcome, "completed")
# TEST-TIER-DISABLED-END tests/test_tool_mapping.py::MapperTools.test_child_post_turn_output_notices_and_retry_keep_parent_attribution

# TEST-TIER-DISABLED-BEGIN tests/test_tool_mapping.py::MapperTools.test_child_request_notice_without_turn_replays_after_spawn_discovery
#     def test_child_request_notice_without_turn_replays_after_spawn_discovery(self) -> None:
#         spawn: Object = {
#             "type": "collabAgentToolCall",
#             "id": "spawn",
#             "tool": "spawnAgent",
#             "status": "inProgress",
#             "receiverThreadIds": [],
#         }
#         self.item("item/started", spawn)
#         self.mapper.consume(
#             "driver/notice", {"threadId": "child", "code": "unexpected_request", "message": "MCP question declined."}
#         )
#         self.assertEqual(len(self.events), 1)
#         self.item("item/completed", {**spawn, "status": "completed", "receiverThreadIds": ["child"]})
#         self.assertEqual(
#             self.events[-1],
#             {
#                 "type": "notice",
#                 "parentCallId": "spawn",
#                 "code": "unexpected_request",
#                 "message": "MCP question declined.",
#             },
#         )
#         self.assertIsNone(self.mapper.agents["child"].mapper)
#         self.assertFalse(self.mapper.foreign_pending)
#         self.assertFalse(any(event.get("type") == "ask_opened" for event in self.events))
#         self.mapper.consume("driver/notice", {"code": "unexpected_request", "message": "Main question declined."})
#         self.assertNotIn("parentCallId", self.events[-1])
#         for malformed in ({"code": "unexpected_request"}, {"message": "missing code"}):
#             with self.assertRaises(Failure):
#                 self.mapper.consume("driver/notice", cast(Object, malformed))
# TEST-TIER-DISABLED-END tests/test_tool_mapping.py::MapperTools.test_child_request_notice_without_turn_replays_after_spawn_discovery

# TEST-TIER-DISABLED-BEGIN tests/test_tool_mapping.py::MapperTools.test_child_other_call_remains_open_after_both_turns_complete
#     def test_child_other_call_remains_open_after_both_turns_complete(self) -> None:
#         self.spawn()
#         item: Object = {
#             "type": "mcpToolCall",
#             "id": "late-mcp",
#             "status": "inProgress",
#             "server": "fixture",
#             "tool": "fixture",
#             "arguments": {},
#         }
#         self.item("item/started", item, "child", "child-turn")
#         self.complete("child", "child-turn")
#         self.complete()
#         self.assertFalse(self.mapper.calls)
#         self.assertFalse(self.mapper.waiting_for_work)
#         self.assertTrue(self.mapper.has_open_calls)
#         self.item("item/completed", {**item, "status": "completed", "result": {"content": []}}, "child", "child-turn")
#         self.assertFalse(self.mapper.has_open_calls)
#         self.assertEqual(self.events[-1]["parentCallId"], "spawn")
# TEST-TIER-DISABLED-END tests/test_tool_mapping.py::MapperTools.test_child_other_call_remains_open_after_both_turns_complete

# Archived complete imports; restore needed names in their original scope, not at this file tail.
# TEST-TIER-IMPORTS-BEGIN tests/test_tool_mapping.py:6
# from arbol_codex_driver.errors import Failure
# TEST-TIER-IMPORTS-END tests/test_tool_mapping.py:6
# TEST-TIER-IMPORTS-BEGIN tests/test_tool_mapping.py:7
# from arbol_codex_driver.json_types import Json, Object, utf8
# TEST-TIER-IMPORTS-END tests/test_tool_mapping.py:7
# TEST-TIER-IMPORTS-BEGIN tests/test_tool_mapping.py:8
# from arbol_codex_driver.run_events import RESULT_LIMIT, RunEvents
# TEST-TIER-IMPORTS-END tests/test_tool_mapping.py:8
