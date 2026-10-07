"""Quota-free run/continuity/stop variants of the retained Codex app-server shapes."""

from __future__ import annotations

import asyncio
import base64
import os
import re
import sys
import time
import tomllib
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from .errors import Failure
from .event_stream import Output
from .input_stream import Input
from .json_types import dumps, loads
from .stand_in import ACCOUNT, CONFIG, SOURCE, VERSION, append_record, environment_checks, fixture_models

type Record = dict[str, Any]
SCENARIOS = {
    "C9",
    "C10",
    "C11",
    "C12",
    "C13",
    "C14",
    "C15",
    "C16",
    "C17",
    "C18",
    "C19",
    "C20",
    "C25",
    "C33",
    "C35",
    "C37",
    "C38",
    "C40",
    "C42",
    "C43",
}
PARTS = {
    "supported",
    "success",
    "plain",
    "hold",
    "malformed",
    "text",
    "structure",
    "dropped-effort",
    "fail",
    "refuse",
    "refuse-stderr",
    "inject-refused",
    "resume-gone",
    "delayed-usage",
    "tool",
    "subagent",
    "subagent-finished",
    "subagent-late",
    "subagent-nested",
    "subagent-discovery",
    "subagent-collab",
    "subagent-collab-discovery",
    "turn-start-race",
    "stubborn",
    "background",
    "linger",
    "stopping",
    "other-call",
    "early-exit",
    "no-requests",
    "collaboration",
    "nested",
    "unexpected-tool",
    "child-late-tool",
}
WORKER_PARTS = {
    "tool",
    "subagent",
    "subagent-finished",
    "subagent-late",
    "subagent-nested",
    "subagent-discovery",
    "subagent-collab",
    "subagent-collab-discovery",
    "turn-start-race",
    "stubborn",
    "background",
    "linger",
    "hold",
}


class RunFixture:
    def __init__(
        self, directory: Path, args: list[str], output: Output, scenario: str, part: str, home: Path, base: Record
    ) -> None:
        self.directory, self.args, self.output, self.scenario, self.part, self.home, self.base = (
            directory,
            args,
            output,
            scenario,
            part,
            home,
            base,
        )
        self.input = Input()
        self.write_lock = asyncio.Lock()
        self.tasks: set[asyncio.Task[None]] = set()
        self.heartbeat: asyncio.Task[None] | None = None
        self.thread_id = "fixture-thread"
        self.turn_id = str(uuid.uuid4()) if scenario == "C14" else "fixture-turn"
        self.child_context: Record = {"threadId": "fixture-subagent-thread", "turnId": "fixture-subagent-turn"}
        self.grandchild_context: Record = {"threadId": "fixture-grandchild-thread", "turnId": "fixture-grandchild-turn"}
        self.initialized = self.configured = self.resumed = self.turn_active = self.subagent_active = (
            self.grandchild_active
        ) = False
        self.logged_in = (home / "auth.json").exists()
        self.thread_params: Record | None = None
        self.history_items: list[Record] = []
        self.saved_path: Path | None = None
        self.start_discovered: Callable[[], Awaitable[None]] | None = None
        self.exit_code: int | None = None
        self.server_requests: dict[str, bool] = {}

    @property
    def context(self) -> Record:
        return {"threadId": self.thread_id, "turnId": self.turn_id}

    def received(self, details: Record | None = None) -> None:
        record = {**self.base, **(details or {})}
        # Owner MCP tables can contain credentials. Even the fixture ledger
        # records their presence and verification only, never their contents.
        request = record.get("request")
        if isinstance(request, dict) and isinstance(request.get("params"), dict):
            clean = dict(request["params"])
            if "config" in clean:
                del clean["config"]
                request = {**request, "params": clean}
                record["request"] = request
                checks = record.get("checks")
                if isinstance(checks, dict) and "input" in checks:
                    record["checks"] = {**checks, "input": request}
        append_record(self.directory, record)

    async def write(self, value: Any) -> None:
        async with self.write_lock:
            await self.output.write(dumps(value) + "\n")

    async def notify(self, method: str, params: Any) -> None:
        await self.write({"method": method, "params": params, "emittedAtMs": int(time.time() * 1000)})

    async def item(self, method: str, value: Any) -> None:
        await self.notify(method, {**self.context, "item": value})

    def later(self, delay: float, callback: Callable[[], Awaitable[None]]) -> asyncio.Task[None]:
        async def delayed() -> None:
            await asyncio.sleep(delay)
            await callback()

        task = asyncio.create_task(delayed())
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    def saved_file(self, id_: str) -> Path:
        return self.home / "sessions/2026/10/07" / f"rollout-2026-10-07T00-00-00-{id_}.jsonl"

    def persist(self) -> None:
        if self.saved_path is None:
            return
        assert self.thread_params is not None
        self.saved_path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        content = (
            dumps(
                {
                    "type": "session_meta",
                    "payload": {
                        "id": self.thread_id,
                        "cwd": self.thread_params["cwd"],
                        "fixtureParams": {key: value for key, value in self.thread_params.items() if key != "config"},
                    },
                }
            )
            + "\n"
        )
        content += "".join(dumps({"type": "response_item", "payload": item}) + "\n" for item in self.history_items)
        fd = os.open(self.saved_path, os.O_WRONLY | os.O_TRUNC | os.O_CREAT, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)

    def thread_result(self) -> Record:
        assert self.thread_params is not None
        params = self.thread_params
        readonly = params["sandbox"] == "read-only"
        effort = None if self.part == "dropped-effort" else params.get("reasoningEffort")
        return {
            "thread": {
                "id": self.thread_id,
                "sessionId": self.thread_id,
                "model": params["model"],
                "modelProvider": "openai",
                "reasoningEffort": effort,
                "preview": "",
                "ephemeral": params.get("ephemeral", False),
                "cwd": params["cwd"],
                "status": {"type": "idle"},
                "turns": [],
                "cliVersion": VERSION,
                "path": str(self.saved_path) if self.saved_path else None,
            },
            "model": params["model"],
            "modelProvider": "openai",
            "serviceTier": params.get("serviceTier"),
            "cwd": params["cwd"],
            "approvalPolicy": "never",
            "sandbox": {
                "type": "readOnly" if readonly else "dangerFullAccess",
                **({"networkAccess": False} if readonly else {}),
            },
            "reasoningEffort": effort,
        }

    async def restored_usage(self) -> None:
        await self.notify(
            "thread/tokenUsage/updated",
            {
                "threadId": self.thread_id,
                "tokenUsage": {
                    "total": {"totalTokens": 900, "inputTokens": 700, "outputTokens": 200},
                    "last": {"totalTokens": 300, "inputTokens": 200, "outputTokens": 100},
                    "modelContextWindow": 258400,
                },
            },
        )

    @staticmethod
    def message(id_: str, text: str) -> Record:
        return {
            "type": "agentMessage",
            "id": id_,
            "text": text,
            "phase": "final_answer",
            "memoryCitation": None,
            "delivery": None,
            "questions": None,
        }

    async def text(self, id_: str, text: str) -> None:
        await self.item("item/started", self.message(id_, ""))
        # These fixtures use ASCII except completed oversized tool results.
        await self.notify("item/agentMessage/delta", {**self.context, "itemId": id_, "delta": text[:2]})
        await self.item("item/completed", self.message(id_, text))

    async def usage(
        self, input_tokens: int, output_tokens: int, last_input: int | None = None, last_output: int | None = None
    ) -> None:
        last_input = input_tokens if last_input is None else last_input
        last_output = output_tokens if last_output is None else last_output
        await self.notify(
            "thread/tokenUsage/updated",
            {
                **self.context,
                "tokenUsage": {
                    "total": {
                        "totalTokens": input_tokens + output_tokens,
                        "inputTokens": input_tokens,
                        "outputTokens": output_tokens,
                    },
                    "last": {
                        "totalTokens": last_input + last_output,
                        "inputTokens": last_input,
                        "outputTokens": last_output,
                    },
                    "modelContextWindow": 258400,
                },
            },
        )

    @staticmethod
    def command(completed: bool, value: str | None = None) -> Record:
        return {
            "type": "commandExecution",
            "id": "fixture-call",
            "pluginId": None,
            "scriptPath": None,
            "command": "printf fixture-output",
            "cwd": os.getcwd(),
            "processId": "12345",
            "source": "unifiedExecStartup",
            "status": "completed" if completed else "inProgress",
            "commandActions": [{"type": "unknown", "command": "printf fixture-output"}],
            "aggregatedOutput": value,
            "exitCode": 0 if completed else None,
            "durationMs": 0 if completed else None,
        }

    async def completed_turn(self, thread: str, id_: str, status: str) -> None:
        await self.notify(
            "turn/completed",
            {
                "threadId": thread,
                "turn": {"id": id_, "items": [], "itemsView": "notLoaded", "status": status, "error": None},
            },
        )

    async def shell_worker(self) -> Record:
        marker = self.directory / f"worker-{os.getpid()}"
        code = "import pathlib,subprocess,sys,time\nchild=subprocess.Popen([sys.executable,'-I','-c','import time; time.sleep(86400)'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)\npathlib.Path(sys.argv[1]).write_text(str(child.pid))\ntime.sleep(86400)\n"
        worker = await asyncio.create_subprocess_exec(
            sys.executable,
            "-I",
            "-c",
            code,
            str(marker),
            start_new_session=True,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        for _ in range(200):
            try:
                raw = marker.read_text()
            except FileNotFoundError:
                raw = ""
            if raw:
                return {"shellPid": worker.pid, "backgroundPid": int(raw)}
            await asyncio.sleep(0.01)
        raise Failure("internal", "The stopping stand-in could not start its shell group.")

    @staticmethod
    def valid_history(items: list[Any]) -> bool:
        ids: set[str] = set()
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                return False
            if item.get("type") == "message":
                content, role = item.get("content"), item.get("role")
                if role not in ("user", "assistant") or not isinstance(content, list):
                    return False
                for part in content:
                    if not isinstance(part, dict) or not (
                        (
                            role == "user"
                            and part.get("type") == "input_image"
                            and isinstance(part.get("image_url"), str)
                            and re.match(r"data:image/(png|jpeg|webp|gif);base64,", part["image_url"])
                        )
                        or (
                            part.get("type") == ("input_text" if role == "user" else "output_text")
                            and isinstance(part.get("text"), str)
                        )
                    ):
                        return False
            elif item.get("type") == "function_call":
                result = items[index + 1] if index + 1 < len(items) else None
                id_ = item.get("call_id")
                if (
                    not isinstance(item.get("name"), str)
                    or not isinstance(item.get("arguments"), str)
                    or not isinstance(id_, str)
                    or re.fullmatch(r"call_[a-zA-Z0-9]{24}", id_) is None
                    or id_ in ids
                    or not isinstance(result, dict)
                    or result.get("type") != "function_call_output"
                    or result.get("call_id") != id_
                    or not isinstance(result.get("output"), str)
                ):
                    return False
                ids.add(id_)
                try:
                    loads(item["arguments"])
                except ValueError:
                    return False
            elif (
                item.get("type") != "function_call_output"
                or not isinstance(item.get("call_id"), str)
                or item["call_id"] not in ids
            ):
                return False
        return True

    async def handle(self, request: Record) -> None:
        method = request.get("method")
        raw_params = request.get("params")
        params: Record = raw_params if isinstance(raw_params, dict) else {}
        if method != "turn/start":
            self.received(
                {
                    "stage": "response" if method is None else "request",
                    "request": request,
                    "checks": {**self.base["checks"], "input": request, "configurationApplied": True},
                }
            )
        if method is None:
            id_ = request.get("id")
            if isinstance(id_, str) and id_ in self.server_requests:
                approve = self.server_requests.pop(id_)
                correct = (
                    request.get("result") == {"decision": "accept"} and "error" not in request
                    if approve
                    else isinstance(request.get("error"), dict)
                    and request["error"].get("code") == -32601
                    and isinstance(request["error"].get("message"), str)
                    and "result" not in request
                )
                if not correct:
                    raise Failure("tool_failed", "The Driver did not settle the unexpected vendor request correctly.")
                if not self.server_requests and self.scenario == "C25":
                    await self.text("permissions-answer", "answer")
                    await self.completed_turn(self.thread_id, self.turn_id, "completed")
                    self.turn_active = False
            return
        if "id" not in request:
            return

        async def answer(result: Any) -> None:
            await self.write({"id": request["id"], "result": result})

        async def error(message: str, code: int = -32602) -> None:
            await self.write({"id": request["id"], "error": {"code": code, "message": message}})

        if method == "initialize" and not self.initialized:
            client = params.get("clientInfo")
            if (
                not isinstance(client, dict)
                or client.get("name") != "arbol-codex-driver"
                or not isinstance(client.get("version"), str)
            ):
                await error("Invalid initialize client identity")
                return
            self.initialized = True
            await answer(
                {
                    "userAgent": f"arbol-codex-driver/{VERSION} (Mac OS 27.0.1; arm64) unknown (arbol-codex-driver; 1.0.0)",
                    "codexHome": str(self.home),
                    "platformFamily": "unix",
                    "platformOs": "macos",
                }
            )
        elif not self.initialized:
            await error("Not initialized")
        elif method == "config/read":
            self.configured = True
            await answer({"config": CONFIG, "origins": {}, "layers": None})
        elif not self.configured:
            await error("Driver configuration was not checked")
        elif method == "account/read":
            await answer({"account": ACCOUNT if self.logged_in else None, "requiresOpenaiAuth": True})
        elif method == "account/login/start":
            await answer(
                {
                    "type": "chatgpt",
                    "loginId": "fixture-login",
                    "authUrl": "https://auth.openai.com/oauth/authorize?redirect_uri=http%3A%2F%2F127.0.0.1%3A1455%2Fauth%2Fcallback&state=fixture",
                }
            )
            fd = os.open(self.home / "auth.json", os.O_WRONLY | os.O_TRUNC | os.O_CREAT, 0o600)
            with os.fdopen(fd, "w") as stream:
                stream.write(dumps({"credential": "fixture-vendor-secret"}))
            self.logged_in = True
            await self.notify(
                "account/login/completed",
                {"loginId": "fixture-login", "success": True, "error": None, "onboardingEntrypoint": None},
            )
            await self.notify("account/updated", {"authMode": "chatgpt", "planType": "fixture"})
        elif method == "model/list":
            if params.get("includeHidden", False) is not False or params.get("cursor") is not None:
                await error("Invalid model list request")
            else:
                await answer({"data": fixture_models(), "nextCursor": None})
        elif method == "thread/start":
            try:
                same_directory = isinstance(params.get("cwd"), str) and Path(params["cwd"]).resolve(
                    strict=True
                ) == Path.cwd().resolve(strict=True)
            except OSError:
                same_directory = False
            if (
                not self.logged_in
                or self.thread_params
                or params.get("model") not in ("gpt-6.1-sol", "gpt-6-astra")
                or not same_directory
                or params.get("approvalPolicy") != "never"
                or params.get("sandbox") not in ("read-only", "danger-full-access")
                or "ephemeral" in params
                and type(params["ephemeral"]) is not bool
                or "developerInstructions" in params
                and not isinstance(params["developerInstructions"], str)
            ):
                await error("Invalid fresh thread configuration")
                return
            self.thread_params = params
            if self.scenario in ("C14", "C38"):
                self.thread_id = str(uuid.uuid4())
            self.saved_path = None if params.get("ephemeral") is True else self.saved_file(self.thread_id)
            self.persist()
            result = self.thread_result()
            await answer(result)
            await self.notify("thread/started", {"thread": result["thread"]})
        elif method == "thread/resume":
            if (
                not self.logged_in
                or self.thread_params
                or not isinstance(params.get("threadId"), str)
                or set(params) - {"threadId", "model", "config"}
                or "model" in params
                and params["model"] not in ("gpt-6.1-sol", "gpt-6-astra")
            ):
                await error("Invalid thread resume configuration")
                return
            if self.part in ("refuse", "refuse-stderr"):
                if self.part == "refuse-stderr":
                    sys.stderr.write("Synthetic thread resume refusal.\n")
                await error("Synthetic thread resume refusal.", -32000)
                return
            try:
                raw = None if self.part == "resume-gone" else self.saved_file(params["threadId"]).read_text()
            except OSError:
                raw = None
            if not raw:
                await error(f"no rollout found for thread id {params['threadId']}", -32600)
                return
            records = [loads(line) for line in raw.strip().splitlines()]
            first: Any = records[0]
            self.thread_params = {
                **first["payload"]["fixtureParams"],
                **({"model": params["model"]} if "model" in params else {}),
                **({"config": params["config"]} if "config" in params else {}),
            }
            self.thread_id = params["threadId"]
            self.history_items = [record["payload"] for record in records[1:] if isinstance(record, dict)]  # type: ignore[misc]
            self.saved_path = self.saved_file(self.thread_id)
            self.resumed = True
            if self.part != "delayed-usage":
                await self.restored_usage()
            await answer(self.thread_result())
        elif method == "thread/inject_items":
            if (
                self.thread_params is None
                or self.resumed
                or params.get("threadId") != self.thread_id
                or not isinstance(params.get("items"), list)
                or set(params) - {"threadId", "items"}
            ):
                await error("Invalid history injection request")
                return
            if self.part in ("refuse", "refuse-stderr", "inject-refused"):
                if self.part == "refuse-stderr":
                    sys.stderr.write("Synthetic native history refusal.\n")
                await error("Synthetic native history refusal.", -32601)
                return
            if not self.valid_history(params["items"]):
                await error("Invalid native history items")
                return
            self.history_items.extend(params["items"])
            self.persist()
            await answer({})
        elif method == "turn/start":
            await self.start_turn(params, request, answer, error)
        elif method == "turn/interrupt":
            self.received(
                {"stage": "interrupt", "request": request, "checks": {**self.base["checks"], "input": request}}
            )
            main = (
                params.get("threadId") == self.thread_id and params.get("turnId") == self.turn_id and self.turn_active
            )
            child = (
                params.get("threadId") == self.child_context["threadId"]
                and params.get("turnId") == self.child_context["turnId"]
                and self.subagent_active
            )
            grandchild = (
                params.get("threadId") == self.grandchild_context["threadId"]
                and params.get("turnId") == self.grandchild_context["turnId"]
                and self.grandchild_active
            )
            if not (main or child or grandchild) or self.part == "stubborn":
                return
            await answer({})
            await self.completed_turn(str(params["threadId"]), str(params["turnId"]), "interrupted")
            if main:
                self.turn_active = False
                if self.start_discovered is not None:
                    self.later(0.01, self.start_discovered)
                    self.start_discovered = None
            if child:
                self.subagent_active = False
                if self.heartbeat is not None:
                    self.heartbeat.cancel()
            if grandchild:
                self.grandchild_active = False
        else:
            await error("This stand-in implements only run app-server requests.", -32601)

    async def start_turn(
        self,
        params: Record,
        request: Record,
        answer: Callable[[Any], Awaitable[None]],
        error: Callable[[str, int], Awaitable[None]],
    ) -> None:
        policy = params.get("sandboxPolicy")
        readonly = (
            isinstance(policy, dict) and policy.get("type") == "readOnly"
            if self.resumed
            else self.thread_params is not None and self.thread_params.get("sandbox") == "read-only"
        )
        inputs = params.get("input")
        if (
            self.thread_params is None
            or params.get("threadId") != self.thread_id
            or not isinstance(inputs, list)
            or not inputs
            or not isinstance(inputs[0], dict)
            or inputs[0].get("type") != "text"
            or not isinstance(inputs[0].get("text"), str)
            or params.get("approvalPolicy") != "never"
            or not isinstance(policy, dict)
            or policy.get("type") != ("readOnly" if readonly else "dangerFullAccess")
            or readonly
            and policy.get("networkAccess") is not False
            or params.get("model") not in ("gpt-6.1-sol", "gpt-6-astra")
            or not self.resumed
            and params.get("model") != self.thread_params["model"]
            or params.get("summary") != "detailed"
            or "serviceTier" in params
            and params["serviceTier"] != "priority"
        ):
            await error("Invalid fresh turn configuration", -32602)
            return
        if self.part == "dropped-effort":
            await error("Requested effort was not applied", -32602)
            return
        if params.get("effort") not in ("low", "medium", "high", "xhigh", "max", "ultra"):
            await error("Invalid turn reasoning effort", -32602)
            return
        if self.resumed and self.part == "delayed-usage":
            await self.restored_usage()
        images: list[Record] = []
        for picture in inputs[1:]:
            if (
                not isinstance(picture, dict)
                or picture.get("type") != "localImage"
                or not isinstance(picture.get("path"), str)
            ):
                raise Failure("tool_failed", "Invalid image input.")
            path = Path(picture["path"])
            images.append(
                {
                    "path": str(path),
                    "data": base64.b64encode(path.read_bytes()).decode(),
                    "mode": path.stat().st_mode & 0o777,
                }
            )
        calls = [item for item in self.history_items if item.get("type") == "function_call"]
        shell = next(
            (
                call
                for call in calls
                if call.get("name") == "shell"
                and isinstance((arguments := loads(str(call["arguments"]))), dict)
                and arguments.get("command") == "printf history-shell-output"
            ),
            None,
        )
        shell_result = next(
            (
                item
                for item in self.history_items
                if shell and item.get("type") == "function_call_output" and item.get("call_id") == shell["call_id"]
            ),
            None,
        )
        foreign = next(
            (
                call
                for call in calls
                if call.get("name") == "foreign_tool"
                and isinstance((arguments := loads(str(call["arguments"]))), dict)
                and arguments.get("value") == "foreign-input"
            ),
            None,
        )
        history_images: list[Record] = []
        for history in self.history_items:
            for part in (
                history.get("content", [])
                if history.get("type") == "message" and isinstance(history.get("content"), list)
                else []
            ):
                if isinstance(part, dict) and part.get("type") == "input_image":
                    match = re.fullmatch(r"data:([^;]+);base64,(.*)", part["image_url"])
                    assert match is not None
                    history_images.append({"mediaType": match[1], "data": match[2]})
        stop_fixture = (
            self.scenario in ("C15", "C17")
            or self.scenario == "C38"
            and self.part == "hold"
            or self.scenario == "C33"
            and self.part == "stopping"
        )
        workers = await self.shell_worker() if stop_fixture and self.part in WORKER_PARTS else None
        checks: Record = {
            **self.base["checks"],
            "input": request,
            "configurationApplied": True,
            "images": images,
            "toolPid": os.getpid(),
            **(workers or {}),
            "backgroundWasAlive": workers is not None,
            "savedPath": str(self.saved_path) if self.saved_path else None,
            "ephemeral": self.thread_params.get("ephemeral") is True,
            "resumed": self.resumed,
            "nativeShellCall": shell is not None,
            **({"nativeShellResult": shell_result["output"]} if shell_result else {}),
            "nativeShellFailed": shell_result is not None
            and isinstance(shell_result.get("output"), str)
            and shell_result["output"].endswith("\nhistory-error"),
            "nativeForeignCall": foreign is not None
            and any(
                item.get("type") == "function_call_output"
                and item.get("call_id") == foreign["call_id"]
                and item.get("output") == '{"value":"foreign-value"}'
                for item in self.history_items
            ),
            "historyImages": history_images,
            "systemPrompt": self.thread_params.get("developerInstructions", ""),
            "nativeHistory": bool(self.history_items),
            "labelledHistory": inputs[0]["text"].startswith("Earlier conversation, for context:"),
            **(
                self.owner_checks(readonly)
                if self.scenario in ("C9", "C37")
                or (Path(os.environ["HOME"]) / ".agents/skills/fixture-skill/SKILL.md").is_file()
                else {}
            ),
        }
        self.received({"stage": "input", "request": request, "checks": checks})
        turn: Record = {
            "id": self.turn_id,
            "items": [],
            "itemsView": "notLoaded",
            "status": "inProgress",
            "error": None,
            "startedAt": None,
            "completedAt": None,
            "durationMs": None,
        }
        if self.part == "turn-start-race":
            await self.notify("turn/started", {"threadId": self.thread_id, "turn": turn})
            self.turn_active = True
            self.received(
                {
                    "stage": "accepted-turn",
                    "checks": {**self.base["checks"], "threadId": self.thread_id, "turnId": self.turn_id},
                }
            )

            async def delayed_answer() -> None:
                await answer({"turn": turn})

            self.later(0.15, delayed_answer)
        else:
            await answer({"turn": turn})
            await self.notify("turn/started", {"threadId": self.thread_id, "turn": turn})
            self.turn_active = True
        input_text = inputs[0]["text"]
        if self.scenario == "C25" and self.part not in ("no-requests", "malformed"):
            await self.unexpected_requests()
            return
        if self.scenario == "C35":
            await self.completed_tools(turn)
            return
        if stop_fixture:
            await self.notify(
                "item/agentMessage/delta", {**self.context, "itemId": "partial-answer", "delta": "partial"}
            )
            await self.usage(3, 2)
            if workers:
                command = {**self.command(False), "processId": "48412", "command": "sleep 60", "cwd": os.getcwd()}
                if self.part.startswith("subagent"):
                    await self.start_subagents(command, turn)
                else:
                    await self.item("item/started", command)
                    if self.part in ("background", "linger"):
                        await self.item(
                            "item/completed",
                            {**command, "status": "completed", "exitCode": 0, "aggregatedOutput": "background-started"},
                        )
            elif self.part == "other-call":
                await self.item(
                    "item/started",
                    {"type": "webSearch", "id": "fixture-other-call", "query": "synthetic unfinished search"},
                )
            if self.part in ("background", "linger", "plain", "other-call", "subagent-late"):
                await self.text("fixture-answer", "answer")
                await self.completed_turn(self.thread_id, self.turn_id, "completed")
                self.turn_active = False
            return
        if input_text == "early-exit":
            self.exit_code = 1
            self.input.close()
            return
        if self.part == "malformed":
            await self.output.write('{"method":\n')
            return
        if input_text == "unknown-request":
            await self.write({"id": "fixture-server-request", "method": "future/request", "params": self.context})
        if self.part == "hold" or input_text == "hold":
            await asyncio.sleep(1.2)
        if self.scenario == "C18" and input_text == "slow":
            for number in range(32):
                await self.text(f"fixture-answer-{number}", "s" * (64 * 1024))
        else:
            await self.text("fixture-answer", "answer")
        if self.scenario == "C13":
            await self.usage(3, 2)
            await self.usage(7, 5, 4, 3)
            await self.usage(7, 5, 4, 3)
        if self.scenario in ("C42", "C14"):
            await self.usage(3, 2)
        if self.scenario in ("C11", "C20", "C42"):
            search = (
                {"type": "webSearch", "id": "fixture-call", "query": "", "action": None, "results": None}
                if self.scenario == "C20" and self.part == "structure"
                else None
            )
            await self.item("item/started", search or self.command(False))
            if self.scenario == "C42":
                self.exit_code = 1
                self.input.close()
                return
            result = "😀" * 60000 if self.scenario == "C20" else "fixture-output"
            completed = (
                {
                    **search,
                    "query": "fixture",
                    "action": {"type": "search", "query": "fixture", "queries": None},
                    "results": [
                        {
                            "type": "text_result",
                            "domain": "example.invalid",
                            "ref_id": "fixture-result",
                            "snippet": result,
                            "title": "Fixture",
                            "url": "https://example.invalid/",
                        }
                    ],
                }
                if search
                else self.command(True, result)
            )
            await self.item("item/completed", completed)
            await self.text("fixture-after-tool", "after-tool")
        failed = self.scenario == "C12" or self.part == "fail" or input_text == "fail"
        if self.scenario in ("C14", "C38"):
            self.history_items.extend(
                [
                    {
                        "type": "message",
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": input_text},
                            *[
                                {
                                    "type": "input_image",
                                    "image_url": f"data:image/{'jpeg' if Path(image['path']).suffix == '.jpg' else Path(image['path']).suffix[1:]};base64,{image['data']}",
                                }
                                for image in images
                            ],
                        ],
                    },
                    {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "answer"}]},
                ]
            )
            self.persist()

        async def finish() -> None:
            self.turn_active = False
            await self.notify(
                "turn/completed",
                {
                    "threadId": self.thread_id,
                    "turn": {
                        **turn,
                        "status": "failed" if failed else "completed",
                        "itemsView": "summary",
                        "error": {
                            "message": "Synthetic vendor failure.",
                            "codexErrorInfo": "other",
                            "additionalDetails": None,
                        }
                        if failed
                        else None,
                    },
                },
            )

        if input_text == "unknown-request":
            self.later(0.075, finish)
        else:
            await finish()

    def owner_checks(self, readonly: bool) -> Record:
        assert self.thread_params is not None
        owner = Path(os.environ["HOME"])
        owner_config = tomllib.loads((owner / ".codex/config.toml").read_text())
        supplied = self.thread_params.get("config")
        expected = {"mcp_servers": owner_config["mcp_servers"]}
        config = tomllib.loads((self.home / "config.toml").read_text())
        skill_path = owner / ".agents/skills/fixture-skill/SKILL.md"
        return {
            "ownerMcpCorrect": supplied is None if readonly else supplied == expected,
            "ownerMcpOmitted": supplied is None,
            "ownerSkillCorrect": skill_path.read_text()
            == "---\nname: fixture-skill\ndescription: A sentinel skill\n---\nSkill sentinel\n",
            "ownerSkillPath": str(skill_path),
            "onlyMemoryFeature": config.get("features") == {"memories": False},
            "liveWebSearch": config.get("web_search") == "live",
            "ownerSettingsAbsent": not any(key in config for key in ("model", "developer_instructions", "mcp_servers")),
        }

    async def unexpected_requests(self) -> None:
        command = {
            **self.context,
            "kind": "command",
            "itemId": "approval-command",
            "startedAtMs": int(time.time() * 1000),
            "environmentId": "local",
            "command": "/bin/zsh -lc 'echo hi'",
            "cwd": os.getcwd(),
            "commandActions": [{"type": "unknown", "command": "echo hi"}],
            "proposedExecpolicyAmendment": ["echo", "hi"],
            "availableDecisions": [
                "accept",
                {"acceptWithExecpolicyAmendment": {"execpolicy_amendment": ["echo", "hi"]}},
                "cancel",
            ],
        }
        patch = {
            **self.context,
            "itemId": "approval-patch",
            "startedAtMs": int(time.time() * 1000),
            "reason": None,
            "grantRoot": None,
        }
        question = {
            **self.context,
            "itemId": "question",
            "questions": [
                {
                    "id": "choice",
                    "header": "Choose",
                    "question": "Choose a fixture colour",
                    "isOther": False,
                    "isSecret": False,
                    "options": [{"label": "Blue", "description": "Fixture colour"}],
                }
            ],
            "isBlocking": True,
            "autoResolutionMs": None,
        }
        requests = [
            ("item/commandExecution/requestApproval", command, True),
            ("item/fileChange/requestApproval", patch, True),
            (
                "item/permissions/requestApproval",
                {**self.context, "itemId": "permissions", "permissions": {"network": {"enabled": True}}},
                False,
            ),
            ("item/tool/call", {**self.context, "callId": "client-tool", "tool": "fixture", "arguments": {}}, False),
            (
                "mcpServer/elicitation/request",
                {
                    **self.context,
                    "serverName": "fixture",
                    "message": "Provide fixture input",
                    "requestedSchema": {"type": "object"},
                },
                False,
            ),
            ("item/tool/requestUserInput", question, False),
            ("future/request", {**self.context}, False),
        ]
        self.server_requests = {f"fixture-request-{index}": approve for index, (_, _, approve) in enumerate(requests)}
        for index, (method, params, _) in enumerate(requests):
            await self.write({"id": f"fixture-request-{index}", "method": method, "params": params})

    async def completed_tools(self, turn: Record) -> None:
        """Recorded item shapes with synthetic refusal and late completion orders."""
        await self.text("main-before", "main-before")
        refused = {
            **self.command(False),
            "id": "refused",
            "command": "/bin/zsh -lc rejected-command",
            "commandActions": [{"type": "unknown", "command": "rejected-command"}],
        }
        await self.item("item/started", refused)
        await self.item(
            "item/completed",
            {**refused, "status": "declined", "aggregatedOutput": "Codex refused this command.", "exitCode": None},
        )
        patch = {
            "type": "fileChange",
            "id": "patch",
            "changes": [
                {"path": str(Path.cwd() / "fixture-patch.txt"), "kind": {"type": "add"}, "diff": "fixture patch\n"}
            ],
            "status": "inProgress",
        }
        search = {"type": "webSearch", "id": "search", "query": "", "action": None, "results": None}
        # MCP success/error envelopes are synthetic protocol variants; the
        # recorded 6 October inference contained no MCP tool call.
        mcp = {
            "type": "mcpToolCall",
            "id": "mcp",
            "server": "fixture",
            "tool": "echo",
            "arguments": {"value": "fixture-value"},
            "status": "inProgress",
            "result": None,
            "error": None,
        }
        for item in (patch, search, mcp):
            await self.item("item/started", item)
        await self.item("item/completed", {**patch, "status": "completed"})
        await self.item(
            "item/completed",
            {
                **search,
                "query": "fixture query",
                "action": {"type": "search", "query": "fixture query", "queries": None},
                "results": [
                    {
                        "type": "text_result",
                        "domain": "example.invalid",
                        "ref_id": "fixture-result",
                        "snippet": "Fixture result",
                        "title": "Fixture",
                        "url": "https://example.invalid/",
                    }
                ],
            },
        )
        await self.item(
            "item/completed",
            {
                **mcp,
                "status": "completed",
                "result": {
                    "content": [{"type": "text", "text": "fixture-value"}],
                    "structuredContent": {"value": "fixture-value"},
                },
            },
        )
        await self.item("item/started", {**mcp, "id": "mcp-failed"})
        await self.item(
            "item/completed",
            {**mcp, "id": "mcp-failed", "status": "failed", "error": {"message": "Fixture MCP refusal."}},
        )
        if self.part == "unexpected-tool":
            await self.text("main-answer", "main-answer")
            await self.completed_turn(self.thread_id, self.turn_id, "completed")
            self.turn_active = False
            return
        child = {"threadId": "agent", "turnId": "agent-turn"}
        activity = {
            "type": "subAgentActivity",
            "id": "agent-started",
            "kind": "started",
            "agentThreadId": "agent",
            "agentPath": "/root/fixture-worker",
        }
        spawn = {
            "type": "collabAgentToolCall",
            "id": "agent-spawn",
            "tool": "spawnAgent",
            "status": "inProgress",
            "senderThreadId": self.thread_id,
            "receiverThreadIds": [],
            "prompt": "Fixture child",
            "model": "",
            "reasoningEffort": "low",
            "agentsStates": {},
        }

        async def child_notices() -> None:
            # Arrive before the child turn and, for collaboration, before its
            # receiver is announced. Request handling must retain wire order.
            self.server_requests["fixture-child-request"] = False
            await self.write(
                {
                    "id": "fixture-child-request",
                    "method": "mcpServer/elicitation/request",
                    "params": {
                        "threadId": "agent",
                        "serverName": "fixture",
                        "message": "Fixture child question",
                        "requestedSchema": {"type": "object"},
                    },
                }
            )
            await self.notify("warning", {"threadId": "agent", "message": "Fixture child warning."})

        if self.part == "collaboration":
            await self.item("item/started", spawn)
            await child_notices()
            await self.notify("turn/started", {"threadId": child["threadId"], "turn": {**turn, "id": child["turnId"]}})
            await self.notify("item/started", {**child, "item": {**self.command(False), "id": "subcall"}})
            await self.item(
                "item/completed",
                {
                    **spawn,
                    "status": "completed",
                    "receiverThreadIds": ["agent"],
                    "agentsStates": {"agent": {"status": "pendingInit", "message": None}},
                },
            )
        else:
            await self.item("item/started", activity)
            await self.item("item/completed", activity)
            await child_notices()
            await self.notify("turn/started", {"threadId": child["threadId"], "turn": {**turn, "id": child["turnId"]}})
            await self.notify("item/started", {**child, "item": {**self.command(False), "id": "subcall"}})
        await self.notify("item/agentMessage/delta", {**child, "itemId": "child-answer", "delta": "sub-agent-only"})
        await self.notify(
            "item/reasoning/summaryTextDelta", {**child, "itemId": "child-reasoning", "delta": "child-thinking"}
        )
        await self.notify("item/commandExecution/outputDelta", {**child, "itemId": "subcall", "delta": "child-output"})
        nested = {"threadId": "nested-agent", "turnId": "nested-turn"}
        nested_activity = {
            **activity,
            "id": "nested-started",
            "agentThreadId": nested["threadId"],
            "agentPath": "/root/fixture-worker/nested",
        }
        if self.part == "nested":
            for method in ("item/started", "item/completed"):
                await self.notify(method, {**child, "item": nested_activity})
            await self.notify(
                "turn/started", {"threadId": nested["threadId"], "turn": {**turn, "id": nested["turnId"]}}
            )
            await self.notify("item/started", {**nested, "item": {**self.command(False), "id": "nested-call"}})
            await self.notify("item/agentMessage/delta", {**nested, "itemId": "nested-answer", "delta": "nested-only"})
        worker = await asyncio.create_subprocess_exec(
            sys.executable,
            "-I",
            "-c",
            "import time; time.sleep(.4); print('background-output')",
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        background = {
            **self.command(False),
            "id": "background",
            "processId": str(worker.pid),
            "command": "/bin/zsh -lc 'sleep .4; echo background-output'",
            "commandActions": [{"type": "unknown", "command": "sleep .4; echo background-output"}],
        }
        await self.item("item/started", background)
        await self.text("main-answer", "main-answer")
        await self.completed_turn(self.thread_id, self.turn_id, "completed")
        self.turn_active = False
        self.received(
            {
                "stage": "main-ended",
                "checks": {
                    **self.base["checks"],
                    "backgroundWasAlive": worker.returncode is None,
                    "childWasActive": True,
                },
            }
        )
        if self.part == "early-exit":
            self.exit_code = 1
            self.input.close()
            return

        async def finish_children() -> None:
            if self.part == "nested":
                await self.notify(
                    "item/completed", {**nested, "item": {**self.command(True, "nested-output"), "id": "nested-call"}}
                )
                await self.notify("item/completed", {**nested, "item": self.message("nested-answer", "nested-only")})
                await self.completed_turn(nested["threadId"], nested["turnId"], "completed")
                for method in ("item/started", "item/completed"):
                    await self.notify(
                        method, {**child, "item": {**nested_activity, "id": "nested-completed", "kind": "completed"}}
                    )
            await self.notify(
                "item/completed", {**child, "item": {**self.command(True, "child-output"), "id": "subcall"}}
            )
            await self.notify("item/completed", {**child, "item": self.message("child-answer", "sub-agent-only")})
            await self.notify(
                "item/completed",
                {**child, "item": {"type": "reasoning", "id": "child-reasoning", "summary": ["child-thinking"]}},
            )
            await self.notify(
                "thread/tokenUsage/updated",
                {
                    **child,
                    "tokenUsage": {
                        "total": {"totalTokens": 5, "inputTokens": 3, "outputTokens": 2},
                        "last": {"totalTokens": 5, "inputTokens": 3, "outputTokens": 2},
                    },
                },
            )
            if self.part == "child-late-tool":
                await self.notify("item/started", {**child, "item": {**mcp, "id": "child-late-mcp"}})
            await self.completed_turn(child["threadId"], child["turnId"], "completed")
            if self.part != "collaboration":
                for method in ("item/started", "item/completed"):
                    await self.item(method, {**activity, "id": "agent-completed", "kind": "completed"})
            self.received({"stage": "child-ended"})

        async def finish_background() -> None:
            output, _ = await worker.communicate()
            await self.notify(
                "item/commandExecution/outputDelta", {**self.context, "itemId": "background", "delta": output.decode()}
            )
            await self.item(
                "item/completed",
                {
                    **background,
                    "status": "completed",
                    "aggregatedOutput": output.decode(),
                    "exitCode": worker.returncode,
                    "durationMs": 400,
                },
            )
            self.received({"stage": "background-ended"})

        self.later(0.15, finish_children)
        self.later(0, finish_background)
        if self.part == "child-late-tool":

            async def finish_child_tool() -> None:
                await self.notify(
                    "item/completed",
                    {**child, "item": {**mcp, "id": "child-late-mcp", "status": "completed", "result": {"late": True}}},
                )
                self.received({"stage": "child-tool-ended"})

            self.later(0.55, finish_child_tool)

    async def start_subagents(self, command: Record, turn: Record) -> None:
        activity: Record = {
            "type": "subAgentActivity",
            "id": "subagent-started-fixture",
            "kind": "started",
            "agentThreadId": self.child_context["threadId"],
            "agentPath": "/root/fixture-worker",
        }
        spawn_call: Record = {
            "type": "collabAgentToolCall",
            "id": "fixture-spawn-call",
            "tool": "spawnAgent",
            "status": "inProgress",
            "senderThreadId": self.thread_id,
            "receiverThreadIds": [],
            "prompt": "Synthetic child job",
            "model": "",
            "reasoningEffort": "low",
            "agentsStates": {},
        }

        async def complete_spawn() -> None:
            await self.notify(
                "turn/started",
                {"threadId": self.child_context["threadId"], "turn": {**turn, "id": self.child_context["turnId"]}},
            )
            await self.item(
                "item/completed",
                {
                    **spawn_call,
                    "status": "completed",
                    "receiverThreadIds": [self.child_context["threadId"]],
                    "model": "gpt-6.1-sol",
                    "agentsStates": {self.child_context["threadId"]: {"status": "pendingInit", "message": None}},
                },
            )

        if self.part.startswith("subagent-collab"):
            await self.item("item/started", spawn_call)
            if self.part == "subagent-collab":
                await complete_spawn()
        else:
            await self.item("item/started", activity)
            await self.item("item/completed", activity)

        async def start_child() -> None:
            if not self.part.startswith("subagent-collab"):
                await self.notify(
                    "turn/started",
                    {"threadId": self.child_context["threadId"], "turn": {**turn, "id": self.child_context["turnId"]}},
                )
            self.subagent_active = True
            await self.notify("item/started", {**self.child_context, "item": {**command, "id": "fixture-subcall"}})
            await self.notify(
                "item/agentMessage/delta", {**self.child_context, "itemId": "subagent-answer", "delta": "child-only"}
            )

        if self.part == "subagent-collab-discovery":

            async def discovered() -> None:
                await complete_spawn()
                await start_child()

            self.start_discovered = discovered
        elif self.part == "subagent-discovery":
            self.start_discovered = start_child
        else:
            await start_child()
        if self.part == "subagent-nested":
            nested = {
                **activity,
                "id": "grandchild-started-fixture",
                "agentThreadId": self.grandchild_context["threadId"],
                "agentPath": "/root/fixture-worker/nested",
            }
            await self.notify("item/started", {**self.child_context, "item": nested})
            await self.notify("item/completed", {**self.child_context, "item": nested})
            await self.notify(
                "turn/started",
                {
                    "threadId": self.grandchild_context["threadId"],
                    "turn": {**turn, "id": self.grandchild_context["turnId"]},
                },
            )
            self.grandchild_active = True
            await self.notify(
                "item/started", {**self.grandchild_context, "item": {**command, "id": "fixture-grandcall"}}
            )
            await self.notify(
                "item/agentMessage/delta",
                {**self.grandchild_context, "itemId": "grandchild-answer", "delta": "grandchild-only"},
            )

        async def ticks() -> None:
            while True:
                await asyncio.sleep(0.02)
                self.received({"stage": "subagent-tick", "checks": {**self.base["checks"], "active": True}})

        self.heartbeat = asyncio.create_task(ticks())
        self.tasks.add(self.heartbeat)
        self.heartbeat.add_done_callback(self.tasks.discard)
        if self.part == "subagent-finished":
            await self.completed_turn(self.thread_id, self.turn_id, "completed")
            self.turn_active = False
        if self.part == "subagent-late":

            async def finish_child() -> None:
                await self.notify(
                    "item/completed",
                    {
                        **self.child_context,
                        "item": {
                            **command,
                            "id": "fixture-subcall",
                            "status": "completed",
                            "exitCode": 0,
                            "aggregatedOutput": "child-result",
                        },
                    },
                )
                await self.notify(
                    "item/completed", {**self.child_context, "item": self.message("subagent-answer", "child-only")}
                )
                await self.completed_turn(
                    str(self.child_context["threadId"]), str(self.child_context["turnId"]), "completed"
                )
                self.subagent_active = False
                if self.heartbeat is not None:
                    self.heartbeat.cancel()
                finished = {**activity, "id": "subagent-completed-fixture", "kind": "completed"}
                await self.item("item/started", finished)
                await self.item("item/completed", finished)

            self.later(0.25, finish_child)

    async def run(self) -> int:
        await self.input.open()
        try:
            while (line := await self.input.line()) is not None:
                request = loads(line)
                if isinstance(request, dict):
                    await self.handle(request)
                if self.exit_code is not None:
                    return self.exit_code
        finally:
            self.input.close()
            if self.heartbeat is not None:
                self.heartbeat.cancel()
            for task in list(self.tasks):
                task.cancel()
            await asyncio.gather(*self.tasks, return_exceptions=True)
        if self.part == "linger":
            self.received({"stage": "stdinEOF"})
        if self.part in ("linger", "stubborn"):
            await asyncio.Event().wait()
        return 0


async def run_stand_in(directory: Path, args: list[str], output: Output) -> int:
    words = (directory / "scenario").read_text().strip().split()
    scenario, part = words[0] if words else "", words[1] if len(words) > 1 else "plain"
    if len(words) > 2 or scenario not in SCENARIOS or part not in PARTS:
        raise Failure("invalid_input", "This stand-in does not implement that run scenario.")
    home = os.environ.get("CODEX_HOME")
    checks = {
        **environment_checks(home),
        "source": SOURCE,
        "synthetic": "Input, tokens, omitted fields, model-effort rejection, failure and oversized-output variants",
    }
    base: Record = {
        "scenario": scenario,
        "part": part,
        "arguments": args,
        "environment": sorted(os.environ),
        "workingDirectory": os.getcwd(),
        "toolVersion": VERSION,
        "checks": checks,
    }
    append_record(directory, base)
    if args == ["--version"]:
        await output.write(f"codex-cli {VERSION}\n")
        return 0
    if args != ["app-server"] or home is None:
        raise Failure("unsupported", "This stand-in requires app-server and a Subscription home.")
    config = (Path(home) / "config.toml").read_text()
    patterns = (
        r"check_for_update_on_startup\s*=\s*false",
        r'web_search\s*=\s*"live"',
        r'cli_auth_credentials_store\s*=\s*"file"',
        r"\[analytics\]\s*enabled\s*=\s*false",
        r"\[features\]\s*memories\s*=\s*false",
    )
    if (
        not checks["privateHome"]
        or not checks["injectedVariablesAbsent"]
        or not all(re.search(pattern, config) for pattern in patterns)
    ):
        raise Failure("tool_failed", "The run stand-in requires the isolated Driver environment and configuration.")
    return await RunFixture(directory, args, output, scenario, part, Path(home), base).run()
