import asyncio
import os
import time
from typing import cast

from test_lifecycle import ENTRY, Fixture

from arbol_codex_driver.continuity import digest
from arbol_codex_driver.json_types import Json, Object, dumps, iso, loads, now, object_value
from arbol_codex_driver.state import owner_json, parse_owner, process_owner, write_json


class Accounts(Fixture):
    async def test_local_concurrent_creation_update_preserves_owner_settings_and_remove_isolated(self) -> None:
        self.scenario("C1 supported")
        replies = await asyncio.gather(
            *(self.invoke(["subscriptions", "create", "--family", "chatgpt", "--label", "Work"]) for _ in range(4))
        )
        ids = sorted(str(object_value(loads(output.decode()))["id"]) for code, output, _ in replies if code == 0)
        self.assertEqual(ids, ["chatgpt-2", "chatgpt-3", "chatgpt-4", "chatgpt-5"])
        record_path = self.state / "subscriptions/chatgpt-2/record.json"
        original = object_value(loads(record_path.read_text()))
        stored: Object = {
            **original,
            "state": "signed_in",
            "account": {"email": "fixture@example.invalid", "plan": "pro"},
            "checkedAt": now(),
            "lastUsage": {"outcome": "ok", "fetchedAt": now(), "windows": []},
        }
        write_json(record_path, stored)
        settings = self.home / ".arbol/arbol-codex-driver.json"
        before = settings.read_text()
        code, output, error = await self.invoke(["subscriptions", "update", "chatgpt-2", "--label", "Renamed"])
        self.assertEqual((code, error), (0, b""))
        changed = object_value(loads(output.decode()))
        self.assertEqual(changed["account"], stored["account"])
        self.assertEqual(changed["lastUsage"], stored["lastUsage"])
        self.assertEqual(changed["createdAt"], stored["createdAt"])
        self.assertEqual(settings.read_text(), before)
        self.assertEqual(await self.invoke(["subscriptions", "remove", "chatgpt-2"]), (0, b"", b""))
        self.assertTrue((self.state / "subscriptions/chatgpt-3/record.json").exists())
        self.assertFalse(record_path.exists())
        self.assertEqual(self.records(), [])
        for id_ in ids[1:]:
            directory = self.state / "subscriptions" / id_
            self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
            self.assertEqual((directory / "record.json").stat().st_mode & 0o777, 0o600)

    async def test_unsigned_refusals_and_malformed_state_do_not_start_vendor_or_disclose_contents(self) -> None:
        self.scenario("C1 supported")
        await self.invoke(["subscriptions", "create", "--family", "chatgpt", "--label", "Unsigned", "--id", "unsigned"])
        for command in ("check", "models"):
            code, output, _ = await self.invoke(["subscriptions", command, "unsigned"])
            self.assertEqual(code, 1)
            self.assertEqual(object_value(object_value(loads(output.decode()))["error"])["code"], "not_signed_in")
        record = self.state / "subscriptions/unsigned/record.json"
        for content in ("null", '"private-malformed"', '{"id":"private-malformed"}'):
            record.write_text(content)
            code, output, error = await self.invoke(["subscriptions", "list"])
            self.assertEqual((code, error), (1, b""))
            self.assertNotIn(b"private-malformed", output)
        self.assertEqual(self.records(), [])

    async def test_usage_last_good_cache_rejection_and_catalog_fallback(self) -> None:
        self.scenario("C1 supported")
        code, output, _ = await self.invoke(["subscriptions", "usage", "chatgpt"])
        self.assertEqual(code, 0)
        fresh = object_value(loads(output.decode()))
        self.assertEqual(fresh["outcome"], "ok")
        self.assertEqual(len(cast(list[Json], fresh["windows"])), 2)
        self.scenario("C1 unavailable")
        _, output, _ = await self.invoke(["subscriptions", "usage", "chatgpt"])
        unavailable = object_value(loads(output.decode()))
        self.assertEqual(unavailable["outcome"], "unavailable")
        self.assertEqual(
            object_value(loads((self.state / "subscriptions/chatgpt/record.json").read_text()))["lastUsage"], fresh
        )
        _, output, _ = await self.invoke(["subscriptions", "models", "chatgpt"])
        self.assertEqual(object_value(loads(output.decode()))["source"], "builtin")
        self.scenario("C1 rejected")
        _, output, _ = await self.invoke(["subscriptions", "usage", "chatgpt"])
        self.assertEqual(object_value(loads(output.decode()))["outcome"], "needs_sign_in")
        record = object_value(loads((self.state / "subscriptions/chatgpt/record.json").read_text()))
        self.assertEqual(record["state"], "needs_attention")
        self.assertEqual(record["lastUsage"], fresh)

    async def test_live_progress_dead_and_reused_owner_recovery(self) -> None:
        self.scenario("C1 supported")
        own = await process_owner(os.getpid())
        assert own is not None
        progress = self.state / "subscriptions/chatgpt/sign-in.json"
        write_json(progress, {"owner": owner_json(own), "expiresAt": iso(time.time() + 300)})
        _, output, _ = await self.invoke(["subscriptions", "list"])
        self.assertEqual(object_value(cast(list[Json], loads(output.decode()))[0])["state"], "signing_in")
        write_json(
            progress,
            {"owner": {**owner_json(own), "startedAt": "1970-01-01T00:00:00Z"}, "expiresAt": iso(time.time() + 300)},
        )
        _, output, _ = await self.invoke(["subscriptions", "list"])
        self.assertEqual(object_value(cast(list[Json], loads(output.decode()))[0])["state"], "signed_in")
        self.assertFalse(progress.exists())
        self.assertEqual(self.records(), [])

    async def test_login_replacement_cancels_pending_and_sign_out_clears_credentials(self) -> None:
        self.scenario("C5 waiting")
        child = await asyncio.create_subprocess_exec(
            str(ENTRY),
            "subscriptions",
            "sign-in",
            "chatgpt",
            "--by-code",
            "--state-dir",
            str(self.state),
            env=self.env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self.children.append(child)
        assert child.stdout is not None
        first = object_value(loads((await asyncio.wait_for(child.stdout.readline(), 3)).decode()))
        self.assertEqual(first["step"], "open_url")
        progress = object_value(loads((self.state / "subscriptions/chatgpt/sign-in.json").read_text()))
        self.owners.append(parse_owner(progress["tool"]))
        self.scenario("C5 success")
        replacement = await self.invoke(["subscriptions", "sign-in", "chatgpt", "--by-code"])
        self.assertEqual(replacement[0], 0)
        remaining, error = await asyncio.wait_for(child.communicate(), 3)
        self.assertEqual((child.returncode, error), (1, b""))
        self.assertEqual(
            object_value(object_value(loads(remaining.decode().splitlines()[-1]))["error"])["code"], "in_use"
        )
        self.assertFalse((self.state / "subscriptions/chatgpt/sign-in.json").exists())
        self.assertEqual((await self.invoke(["subscriptions", "sign-out", "chatgpt"]))[0], 0)
        self.assertFalse((self.state / "subscriptions/chatgpt/home/auth.json").exists())


class Continuity(Fixture):
    async def request_run(self, fields: Object, part: str = "plain", outcome: str = "completed") -> list[Object]:
        self.scenario("C14 " + part)
        path = self.home / "request.json"
        path.write_text(
            dumps(
                {
                    "runId": "continuity",
                    "chatSessionId": "opaque/../chat",
                    "workingDirectory": str(self.home),
                    "tools": "none",
                    "history": [],
                    "input": {"role": "user", "text": "hello"},
                    **fields,
                }
            )
        )
        code, output, error = await self.invoke(["run", "--request", str(path)])
        self.assertEqual((code, error), (0 if outcome == "completed" else 1, b""))
        events = [object_value(loads(raw)) for raw in output.decode().splitlines()]
        self.assertEqual(events[-1]["outcome"], outcome)
        self.assertEqual(sum(event["type"] == "finished" for event in events), 1)
        self.assertEqual([event["seq"] for event in events], list(range(1, len(events) + 1)))
        return events

    def history(self, input_: Object, events: list[Object], prior: list[Json] | None = None) -> list[Json]:
        return [
            *(prior or []),
            {"type": "message", **input_},
            *(
                {"type": "message", "role": "assistant", "text": event["text"]}
                for event in events
                if event["type"] == "text" and "parentCallId" not in event
            ),
        ]

    async def test_resume_overrides_and_delayed_restored_usage_do_not_count_previous_thread(self) -> None:
        input_: Object = {"role": "user", "text": "hello", "images": [{"mediaType": "image/png", "data": "aQ=="}]}
        first = await self.request_run({"input": input_, "systemPrompt": "exact\ninstructions\n"})
        self.assertEqual(next(event for event in first if event["type"] == "started")["continuity"], "fresh")
        history = self.history(input_, first)
        for part in ("plain", "delayed-usage"):
            events = await self.request_run(
                {
                    "history": history,
                    "systemPrompt": "exact\ninstructions\n",
                    "model": "gpt-6-astra",
                    "effort": "high",
                    "serviceTier": "priority",
                },
                part,
            )
            started = next(event for event in events if event["type"] == "started")
            self.assertEqual(started["continuity"], "resumed")
            self.assertEqual(started["model"], "gpt-6-astra")
            self.assertEqual(object_value(events[-1]["usage"])["inputTokens"], 3)
            self.assertEqual(object_value(events[-1]["usage"])["outputTokens"], 2)
            history = self.history({"role": "user", "text": "hello"}, events, history)

    async def test_native_history_and_visible_text_fallback_preserve_tools_images_and_system_prompt(self) -> None:
        history: list[Json] = [
            {
                "type": "message",
                "role": "user",
                "text": "earlier",
                "images": [{"mediaType": "image/png", "data": "aQ=="}],
            },
            {
                "type": "tool_call",
                "name": "shell",
                "input": {"command": "printf history-shell-output", "cwd": str(self.home)},
                "ok": False,
                "result": {"output": "history-output", "exitCode": 2},
                "error": "history-error",
            },
            {
                "type": "tool_call",
                "name": "foreign_tool",
                "input": {"value": "foreign-input"},
                "ok": True,
                "result": {"value": "foreign-value"},
            },
            {"type": "message", "role": "assistant", "text": "reply"},
        ]
        for part in ("plain", "inject-refused"):
            events = await self.request_run(
                {
                    "chatSessionId": part,
                    "history": history,
                    "systemPrompt": "exact-system",
                    "input": {"role": "user", "text": "new", "images": [{"mediaType": "image/jpeg", "data": "b2s="}]},
                },
                part,
            )
            checks = object_value((await self.until_record("input"))["checks"])
            self.assertEqual(checks["systemPrompt"], "exact-system")
            pictures = cast(list[Json], checks["images"])
            if part == "plain":
                self.assertTrue(checks["nativeShellCall"])
                self.assertTrue(checks["nativeShellFailed"])
                self.assertTrue(checks["nativeForeignCall"])
                self.assertEqual(len(pictures), 1)
            else:
                self.assertTrue(checks["labelledHistory"])
                self.assertEqual([object_value(picture)["data"] for picture in pictures], ["aQ==", "b2s="])
                self.assertTrue(any(event.get("code") == "history_as_text" for event in events))
            self.assertFalse((self.state / "tmp/continuity").exists())

    async def test_resume_vendor_refusal_and_missing_rollout_rebuild_then_failed_resume_invalidates_map(self) -> None:
        for part, reason in (("resume-gone", "conversation_gone"), ("refuse", "resume_refused")):
            first = await self.request_run({"chatSessionId": part})
            history = self.history({"role": "user", "text": "hello"}, first)
            next_ = await self.request_run({"chatSessionId": part, "history": history}, part)
            started = next(event for event in next_ if event["type"] == "started")
            self.assertEqual((started["continuity"], started["rebuildReason"]), ("rebuilt", reason))
            history = self.history({"role": "user", "text": "hello"}, next_, history)
            await self.request_run({"chatSessionId": part, "history": history}, "fail", "failed")
            self.assertFalse((self.state / "subscriptions/chatgpt/chats" / (digest(part) + ".json")).exists())
