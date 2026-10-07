import tempfile
import unittest
from pathlib import Path
from typing import cast

from arbol_codex_driver.errors import Failure
from arbol_codex_driver.json_types import Json, Object, dumps, object_value, utf8
from arbol_codex_driver.run_events import RESULT_LIMIT, RunEvents, plain_command, truncate_result
from arbol_codex_driver.run_request import read_run_request


class Requests(unittest.IsolatedAsyncioTestCase):
    async def test_request_precedence_private_input_and_opaque_labels(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            old, new = folder / "old", folder / "new"
            old.mkdir()
            new.mkdir()
            prompt = folder / "prompt.txt"
            prompt.write_text('Exact instructions\nwith "quotes".\n')
            request = folder / "request.json"
            source = dumps(
                {
                    "history": [],
                    "tools": "none",
                    "model": "old-model",
                    "effort": "low",
                    "serviceTier": "flex",
                    "workingDirectory": str(old),
                    "runId": "file-run",
                    "input": {"role": "user", "text": "old", "images": [{"mediaType": "image/png", "data": "aQ=="}]},
                    "labels": {"source": "file", "__proto__": "opaque"},
                }
            )
            request.write_text(source)
            result = await read_run_request(
                {
                    "request": str(request),
                    "model": "new-model",
                    "effort": "high",
                    "service-tier": "priority",
                    "cwd": str(new),
                    "run-id": "cli-run",
                    "system-prompt-file": str(prompt),
                    "label": ["__proto__=cli", "empty=", "equals=a=b"],
                    "control": True,
                    "output": "text",
                },
                message="new",
            )
            self.assertEqual(
                (result.model, result.effort, result.service_tier, result.run_id),
                ("new-model", "high", "priority", "cli-run"),
            )
            self.assertEqual(
                result.input, {"role": "user", "text": "new", "images": [{"mediaType": "image/png", "data": "aQ=="}]}
            )
            self.assertEqual(result.labels, {"source": "file", "__proto__": "cli", "empty": "", "equals": "a=b"})
            self.assertEqual(result.system_prompt, prompt.read_text())
            self.assertEqual(result.working_directory, str(new.resolve()))
            self.assertTrue(result.control)
            self.assertEqual(result.output, "text")
            self.assertEqual(request.read_text(), source)

    async def test_request_defaults_and_ignored_settings_effort_provenance(self) -> None:
        minimal = await read_run_request({}, message="hello")
        self.assertEqual(
            (
                minimal.subscription_id,
                minimal.model,
                minimal.effort,
                minimal.tools,
                minimal.history,
                minimal.search_path,
            ),
            ("chatgpt", None, None, "none", [], []),
        )
        configured = await read_run_request(
            {},
            settings={
                "defaultSubscription": "work",
                "subscriptions": {"work": {"defaultModel": "configured", "defaultEffort": "medium"}},
            },
            message="hello",
        )
        self.assertEqual(
            (configured.subscription_id, configured.model, configured.effort), ("work", "configured", "medium")
        )
        self.assertTrue(configured.effort_from_settings)
        self.assertFalse((await read_run_request({"effort": "high"}, message="hello")).effort_from_settings)

    async def test_request_malformed_images_history_limits_and_identity_before_refusal(self) -> None:
        base: Object = {"history": [], "tools": "none", "input": {"role": "user", "text": "hello"}}
        values = cast(
            list[Json],
            [
                None,
                [],
                {},
                *(
                    {**base, key: value}
                    for key, value in (
                        ("runId", "../bad"),
                        ("model", ""),
                        ("effort", 1),
                        ("labels", {"key": 2}),
                        ("labels", []),
                        ("history", {}),
                        ("tools", "some"),
                        ("limits", {"totalSeconds": -1}),
                        ("limits", {"idleSeconds": True}),
                        ("limits", {"startSeconds": 1}),
                        ("searchPath", ["relative"]),
                    )
                ),
                {**base, "input": {"role": "assistant", "text": "bad"}},
                {**base, "history": [None]},
                {**base, "history": [{"type": "message", "role": "system", "text": "bad"}]},
                {**base, "history": [{"type": "tool_call", "name": "shell", "input": {}, "ok": True}]},
            ],
        )
        for image in (
            None,
            {"mediaType": "application/pdf", "data": "aQ=="},
            {"mediaType": "image/png", "data": ""},
            {"mediaType": "image/png", "data": "aQ"},
            {"mediaType": "image/png", "data": "a==="},
            {"mediaType": "image/png", "data": "a Q="},
            {"mediaType": "image/png", "data": 12},
        ):
            values.append(
                {
                    **base,
                    "input": {
                        "role": "user",
                        "text": "hello",
                        "images": None if image is None else [cast(Json, image)],
                    },
                }
            )
        for value in values:

            async def line(value: Json = value) -> str:
                return dumps(value)

            with self.subTest(value=value), self.assertRaises(Failure) as caught:
                await read_run_request({"request": "-"}, first_line=line)
            self.assertEqual(caught.exception.result["code"], "invalid_input")

        async def nonfinite() -> str:
            return (
                '{"history":[],"tools":"none","input":{"role":"user","text":"hello"},"limits":{"totalSeconds":1e999}}'
            )

        with self.assertRaises(Failure):
            await read_run_request({"request": "-"}, first_line=nonfinite)
        identities: list[Json] = []

        async def missing_folder() -> str:
            return dumps(
                {
                    **base,
                    "runId": "kept",
                    "labels": {"__proto__": "opaque"},
                    "workingDirectory": "/nonexistent/arbol-folder",
                }
            )

        with self.assertRaises(Failure):
            await read_run_request(
                {"request": "-"},
                first_line=missing_folder,
                identity=lambda id_, labels: identities.append({"id": id_, "labels": labels}),
            )
        self.assertEqual(identities, [{"id": "kept", "labels": {"__proto__": "opaque"}}])

    async def test_request_large_stdin_line_is_not_vendor_frame_bound(self) -> None:
        text = "x" * (4 * 1024 * 1024 + 1)

        async def line() -> str:
            return dumps({"history": [], "tools": "none", "input": {"role": "user", "text": text}})

        self.assertEqual((await read_run_request({"request": "-"}, first_line=line)).input["text"], text)


class Mapper(unittest.TestCase):
    def setUp(self) -> None:
        self.events: list[Object] = []
        self.mapper = RunEvents(
            "thread", "turn", "model", lambda type_, data: self.events.append({"type": type_, **data})
        )

    def notify(self, method: str, data: Object) -> None:
        self.mapper.consume(method, {"threadId": "thread", "turnId": "turn", **data})

    def item(self, method: str, item: Object) -> None:
        self.notify(method, {"item": item})

    def complete(self, status: str = "completed", error: Json = None) -> None:
        self.mapper.consume(
            "turn/completed", {"threadId": "thread", "turn": {"id": "turn", "status": status, "error": error}}
        )

    def test_text_authoritative_blocks_reasoning_usage_dedup_and_reroute(self) -> None:
        self.notify("item/agentMessage/delta", {"delta": "partial"})
        self.item("item/completed", {"type": "agentMessage", "id": "a", "text": "authoritative"})
        self.notify("item/reasoning/summaryTextDelta", {"delta": "reason"})
        self.item("item/completed", {"type": "reasoning", "id": "r", "summary": ["First", "Second"]})
        self.assertEqual(
            self.events,
            [
                {"type": "text_delta", "text": "partial"},
                {"type": "text", "text": "authoritative"},
                {"type": "thinking_delta", "text": "reason"},
                {"type": "thinking", "text": "First\n\nSecond"},
            ],
        )
        for total, last in (
            ({"inputTokens": 3, "outputTokens": 2}, {"inputTokens": 3, "outputTokens": 2}),
            ({"inputTokens": 7, "outputTokens": 5}, {"inputTokens": 4, "outputTokens": 3}),
            ({"inputTokens": 7, "outputTokens": 5}, {"inputTokens": 4, "outputTokens": 3}),
        ):
            self.notify(
                "thread/tokenUsage/updated", {"tokenUsage": {"total": cast(Object, total), "last": cast(Object, last)}}
            )
        self.assertEqual(self.mapper.usage, {"model": "model", "inputTokens": 7, "outputTokens": 5})
        snapshot = self.mapper.usage
        snapshot["inputTokens"] = 100
        self.assertEqual(self.mapper.usage["inputTokens"], 7)
        self.notify("model/rerouted", {"toModel": "actual", "reason": "rateLimit"})
        self.assertEqual(self.mapper.usage["model"], "actual")
        self.assertNotIn("costUsd", self.mapper.usage)

    def test_shell_mapping_late_results_failures_and_interrupted_calls_once(self) -> None:
        self.item(
            "item/started",
            {
                "type": "commandExecution",
                "id": "shell",
                "command": "/bin/zsh -lc 'printf fixture-output'",
                "cwd": "/work",
                "status": "inProgress",
            },
        )
        self.complete()
        self.notify("item/commandExecution/outputDelta", {"itemId": "shell", "delta": "late output"})
        self.item(
            "item/completed",
            {"type": "commandExecution", "id": "shell", "status": "completed", "exitCode": 0, "aggregatedOutput": None},
        )
        self.assertEqual(
            self.events[0],
            {
                "type": "tool_started",
                "callId": "shell",
                "name": "shell",
                "input": {"command": "printf fixture-output", "cwd": "/work"},
            },
        )
        self.assertEqual(
            self.events[-1],
            {
                "type": "tool_finished",
                "callId": "shell",
                "ok": True,
                "result": {"output": "late output", "exitCode": 0},
            },
        )
        self.item("item/started", {"type": "webSearch", "id": "unfinished", "query": "query"})
        self.mapper.close_open_calls()
        self.mapper.close_open_calls()
        self.item("item/completed", {"type": "webSearch", "id": "unfinished", "query": "query"})
        self.assertEqual(self.mapper.unfinished_calls, ["unfinished"])
        self.assertEqual(
            sum(item["type"] == "tool_finished" and item.get("callId") == "unfinished" for item in self.events), 1
        )
        self.assertFalse(any(item["type"] == "finished" for item in self.events))
        for code, status in ((2, "completed"), (None, "declined"), (None, "failed")):
            self.item("item/started", {"type": "commandExecution", "id": str(status), "command": "false"})
            self.item(
                "item/completed", {"type": "commandExecution", "id": str(status), "status": status, "exitCode": code}
            )
            self.assertIs(self.events[-1]["ok"], False)

    def test_collaboration_concurrent_receivers_and_nested_spawn_discovery(self) -> None:
        for id_ in ("a", "b"):
            self.item(
                "item/started",
                {
                    "type": "collabAgentToolCall",
                    "id": id_,
                    "tool": "spawnAgent",
                    "status": "inProgress",
                    "receiverThreadIds": [],
                },
            )
        for id_ in ("child-a", "unrelated", "child-b"):
            self.mapper.consume("item/agentMessage/delta", {"threadId": id_, "turnId": id_ + "-turn", "delta": id_})
        for id_ in ("a", "b"):
            self.item(
                "item/completed",
                {
                    "type": "collabAgentToolCall",
                    "id": id_,
                    "tool": "spawnAgent",
                    "status": "completed",
                    "receiverThreadIds": ["child-" + id_],
                },
            )
        self.assertEqual(
            self.mapper.active_turns,
            [
                {"threadId": "thread", "turnId": "turn"},
                {"threadId": "child-a", "turnId": "child-a-turn"},
                {"threadId": "child-b", "turnId": "child-b-turn"},
            ],
        )
        self.assertEqual(sum(item.get("code") == "foreign_thread" for item in self.events), 1)
        self.assertFalse(any(item.get("text") == "unrelated" for item in self.events))
        nested: Object = {
            "type": "collabAgentToolCall",
            "id": "nested",
            "tool": "spawnAgent",
            "status": "inProgress",
            "receiverThreadIds": [],
        }
        self.mapper.consume("item/started", {"threadId": "child-a", "turnId": "child-a-turn", "item": nested})
        self.mapper.consume("turn/started", {"threadId": "grandchild", "turn": {"id": "grandchild-turn"}})
        self.mapper.consume(
            "item/completed",
            {
                "threadId": "child-a",
                "turnId": "child-a-turn",
                "item": {**nested, "status": "completed", "receiverThreadIds": ["grandchild"]},
            },
        )
        self.mapper.consume(
            "item/agentMessage/delta", {"threadId": "grandchild", "turnId": "grandchild-turn", "delta": "nested-output"}
        )
        self.assertIn({"type": "text_delta", "text": "nested-output", "parentCallId": "nested"}, self.events)
        self.assertTrue(any(turn["threadId"] == "grandchild" for turn in self.mapper.active_turns))

    def test_protocol_malformed_foreign_notices_outcome_and_utf8_truncation(self) -> None:
        for id_ in ("foreign", "another"):
            self.mapper.consume("item/agentMessage/delta", {"threadId": id_, "turnId": "turn", "delta": "private"})
        self.assertEqual(len(self.events), 1)
        for method, value in (
            ("item/agentMessage/delta", {"threadId": "thread", "turnId": "turn", "delta": 1}),
            ("thread/status/changed", {"threadId": "thread", "turnId": "other"}),
            ("thread/tokenUsage/updated", {"threadId": "thread", "turnId": "turn", "tokenUsage": {}}),
            ("turn/completed", None),
        ):
            with self.assertRaises(Failure):
                self.mapper.consume(method, cast(Json, value))
        self.notify("error", {"error": {"message": "vendor failed"}, "willRetry": False})
        self.complete()
        self.assertEqual(self.mapper.outcome, "failed")
        self.assertEqual(object_value(self.mapper.error)["code"], "vendor_error")
        for raw in ("🌲" * RESULT_LIMIT, {"content": "🌲" * RESULT_LIMIT}):
            result = truncate_result(cast(Json, raw))
            self.assertTrue(result["truncated"])
            self.assertLessEqual(len(utf8(str(result["result"]))), RESULT_LIMIT)
            self.assertNotIn("�", str(result["result"]))
        self.assertEqual(
            truncate_result({"output": "small", "exitCode": 0}), {"result": {"output": "small", "exitCode": 0}}
        )

    def test_shell_unwrap_preserves_quoting(self) -> None:
        self.assertEqual(plain_command("/bin/zsh -lc 'echo hi'"), "echo hi")
        self.assertEqual(plain_command("/bin/bash -c 'printf '\\''single'\\'''"), "printf 'single'")
        self.assertEqual(plain_command('/bin/sh -c "echo \\$HOME"'), "echo $HOME")
        for command in ('echo "$HOME"', 'bash -lc "echo hi" extra', 'zsh -c "unterminated', "echo a && echo b"):
            self.assertEqual(plain_command(command), command)
