import re
from collections.abc import Callable
from dataclasses import dataclass

from .errors import Failure
from .json_types import Json, Object, dumps, number, object_value, string, utf8

RESULT_LIMIT = 200 * 1024


def protocol_failure() -> Failure:
    return Failure("tool_failed", "codex returned a malformed run notification.")


def prefix(text: str, limit: int = RESULT_LIMIT) -> tuple[str, bool]:
    raw = utf8(text)
    return (raw[:limit].decode("utf-8", "ignore"), True) if len(raw) > limit else (text, False)


def truncate_result(result: Json) -> Object:
    text, cut = prefix(result if isinstance(result, str) else dumps(result))
    return {"result": text, "truncated": True} if cut else {"result": result}


def plain_command(command: str) -> str:
    words: list[str] = []
    word, quote, present = "", "", False
    index = 0
    while index < len(command):
        char = command[index]
        if quote == "'":
            if char == "'":
                quote = ""
            else:
                word += char
        elif char == '"':
            quote = "" if quote == '"' else '"'
            present = True
        elif not quote and char == "'":
            quote, present = "'", True
        elif char == "\\" and (not quote or index + 1 < len(command) and command[index + 1] in '$`"\\\n'):
            index += 1
            if index == len(command):
                return command
            if command[index] != "\n":
                word += command[index]
            present = True
        elif not quote and char.isspace():
            if present:
                words.append(word)
                word, present = "", False
        else:
            word += char
            present = True
        index += 1
    if quote:
        return command
    if present:
        words.append(word)
    if (
        len(words) == 3
        and re.search(r"(?:^|/)(?:sh|bash|zsh|dash|ksh|fish)$", words[0])
        and re.fullmatch(r"-[il]*c[il]*", words[1])
    ):
        return words[2]
    return command


def vendor_failure(error: Json) -> Object:
    return Failure("vendor_error", string(object_value(error).get("message")) or "codex failed the turn.").result


@dataclass
class Call:
    name: str
    type: str
    output: str = ""
    output_cut: bool = False


@dataclass
class Agent:
    parent_call_id: str
    path: str | None = None
    active: bool = True
    mapper: RunEvents | None = None


class RunEvents:
    def __init__(self, thread_id: str, turn_id: str, model: str, emit: Callable[[str, Object], None]) -> None:
        self.thread_id, self.turn_id, self.emit = thread_id, turn_id, emit
        self.totals: Object = {"model": model}
        self.last_total: str | None = None
        self.foreign_notice = False
        self.calls: dict[str, Call] = {}
        self.closed: set[str] = set()
        self.interrupted: dict[str, None] = {}
        self.completed_items: set[str] = set()
        self.agents: dict[str, Agent] = {}
        self.foreign_pending: list[tuple[str, Object]] = []
        self.output_produced = False
        self.outcome: str | None = None
        self.error: Object | None = None

    @property
    def usage(self) -> Object:
        return self.totals.copy()

    @property
    def unfinished_calls(self) -> list[Json]:
        return [
            *self.interrupted,
            *self.calls,
            *(
                call
                for agent in self.agents.values()
                if agent.mapper is not None
                for call in agent.mapper.unfinished_calls
            ),
        ]

    def knows_thread(self, id_: str) -> bool:
        return (
            id_ == self.thread_id
            or id_ in self.agents
            or any(agent.mapper is not None and agent.mapper.knows_thread(id_) for agent in self.agents.values())
        )

    @property
    def active_turns(self) -> list[Object]:
        result: list[Object] = []
        if self.outcome is None:
            result.append({"threadId": self.thread_id, "turnId": self.turn_id})
        for agent in self.agents.values():
            if agent.mapper is not None:
                result.extend(agent.mapper.active_turns)
        return result

    @property
    def waiting_for_work(self) -> bool:
        return any(call.type == "commandExecution" for call in self.calls.values()) or any(
            agent.active or agent.mapper is not None and agent.mapper.waiting_for_work for agent in self.agents.values()
        )

    @property
    def has_pending_spawns(self) -> bool:
        return any(
            call.type == "collabAgentToolCall" and call.name == "spawnAgent" for call in self.calls.values()
        ) or any(agent.mapper is not None and agent.mapper.has_pending_spawns for agent in self.agents.values())

    @property
    def has_active_agents(self) -> bool:
        return self.has_pending_spawns or any(
            agent.active or agent.mapper is not None and agent.mapper.has_active_agents
            for agent in self.agents.values()
        )

    def close_open_calls(self, message: str = "The run ended before the tool call finished.") -> None:
        for agent in self.agents.values():
            if agent.mapper is not None:
                agent.mapper.close_open_calls(message)
        for call_id in self.calls:
            self.interrupted[call_id] = None
            self.closed.add(call_id)
            self.emit("tool_finished", {"callId": call_id, "ok": False, "error": message, "interrupted": True})
        self.calls.clear()

    def identity(self, params: Object, turn_id: Json = None) -> None:
        if (
            params.get("threadId") != self.thread_id
            or (params.get("turnId") if turn_id is None else turn_id) != self.turn_id
        ):
            raise protocol_failure()

    def ignore_foreign(self) -> None:
        if not self.foreign_notice:
            self.foreign_notice = True
            self.emit(
                "notice", {"code": "foreign_thread", "message": "A notification for another codex thread was ignored."}
            )

    def replay_foreign(self) -> None:
        pending, self.foreign_pending = self.foreign_pending, []
        for method, params in pending:
            thread = string(params.get("threadId"))
            if thread is not None and self.knows_thread(thread):
                self.consume(method, params)
            elif self.has_pending_spawns:
                self.foreign_pending.append((method, params))
            else:
                self.ignore_foreign()

    def text(self, type_: str, text: str) -> None:
        if text:
            self.output_produced = True
            self.emit(type_, {"text": text})

    def consume(self, method: str, value: Json) -> None:
        if not isinstance(value, dict):
            if method.startswith("item/") or method in (
                "turn/completed",
                "thread/tokenUsage/updated",
                "error",
                "warning",
                "model/rerouted",
                "deprecationNotice",
            ):
                raise protocol_failure()
            return
        params = value
        foreign_thread = string(params.get("threadId"))
        if foreign_thread is not None and foreign_thread != self.thread_id:
            ancestor = next(
                (
                    agent
                    for agent in self.agents.values()
                    if agent.mapper is not None and agent.mapper.knows_thread(foreign_thread)
                ),
                None,
            )
            if ancestor is not None and ancestor.mapper is not None and foreign_thread not in self.agents:
                ancestor.mapper.consume(method, params)
                self.replay_foreign()
                return
            agent = self.agents.get(foreign_thread)
            if agent is not None:
                turn_id = string(params.get("turnId")) or string(object_value(params.get("turn")).get("id"))
                if turn_id is not None:
                    if agent.mapper is None or method == "turn/started" and agent.mapper.outcome is not None:

                        def child_emit(type_: str, data: Object) -> None:
                            assert agent is not None
                            self.emit(type_, {"parentCallId": agent.parent_call_id, **data})

                        agent.mapper = RunEvents(foreign_thread, turn_id, str(self.totals.get("model", "")), child_emit)
                        agent.active = True
                    agent.mapper.consume(method, params)
                    if method == "turn/completed":
                        agent.active = False
                self.replay_foreign()
                return
            if self.has_pending_spawns:
                self.foreign_pending.append((method, params))
            else:
                self.ignore_foreign()
            return
        turn = object_value(params.get("turn"))
        current_turn_id = params.get("turnId", turn.get("id"))
        if params.get("threadId") == self.thread_id and current_turn_id is not None and current_turn_id != self.turn_id:
            raise Failure("tool_failed", "codex sent a notification for another turn of the run thread.")
        if method in ("item/agentMessage/delta", "item/reasoning/summaryTextDelta"):
            self.identity(params)
            if not isinstance(params.get("delta"), str):
                raise protocol_failure()
            self.text("text_delta" if method == "item/agentMessage/delta" else "thinking_delta", str(params["delta"]))
        elif method in ("item/started", "item/completed"):
            self.identity(params)
            item = object_value(params.get("item"))
            if not isinstance(item.get("type"), str) or not isinstance(item.get("id"), str) or not item["id"]:
                raise protocol_failure()
            type_, id_ = str(item["type"]), str(item["id"])
            if type_ == "subAgentActivity":
                self.agent_activity(item)
            elif type_ in ("userMessage", "hookPrompt", "contextCompaction", "functionCallOutput"):
                pass
            elif type_ in ("agentMessage", "reasoning"):
                if method == "item/started" or id_ in self.completed_items:
                    return
                if type_ == "agentMessage":
                    if not isinstance(item.get("text"), str):
                        raise protocol_failure()
                    self.text("text", str(item["text"]))
                else:
                    summary = item.get("summary", [])
                    if not isinstance(summary, list) or any(not isinstance(part, str) for part in summary):
                        raise protocol_failure()
                    self.text("thinking", "\n\n".join(str(part) for part in summary))
                self.completed_items.add(id_)
            elif method == "item/started":
                self.start_call(item)
            else:
                self.finish_call(item)
        elif method == "item/commandExecution/outputDelta":
            self.identity(params)
            output_id, delta = string(params.get("itemId")), string(params.get("delta"))
            call = self.calls.get(output_id or "")
            if output_id is None or delta is None or call is None or call.type != "commandExecution":
                raise protocol_failure()
            self.emit("tool_output_delta", {"callId": output_id, "text": delta})
            if not call.output_cut:
                call.output, call.output_cut = prefix(call.output + delta)
        elif method == "thread/tokenUsage/updated":
            self.identity(params)
            usage = object_value(params.get("tokenUsage"))
            if not isinstance(usage.get("last"), dict):
                raise protocol_failure()
            last, total = object_value(usage["last"]), usage.get("total")
            marker = (
                dumps(
                    [
                        total.get(key)
                        for key in (
                            "totalTokens",
                            "inputTokens",
                            "cachedInputTokens",
                            "outputTokens",
                            "reasoningOutputTokens",
                        )
                    ]
                )
                if isinstance(total, dict)
                else None
            )
            if marker is None or marker != self.last_total:
                for vendor, key in (
                    ("inputTokens", "inputTokens"),
                    ("cachedInputTokens", "cachedInputTokens"),
                    ("outputTokens", "outputTokens"),
                    ("reasoningOutputTokens", "reasoningTokens"),
                ):
                    count = last.get(vendor)
                    if number(count) and isinstance(count, (int, float)) and count >= 0:
                        current = self.totals.get(key, 0)
                        assert isinstance(current, (int, float))
                        self.totals[key] = current + count
                self.last_total = marker
            self.emit("usage", {"usage": self.usage})
        elif method == "model/rerouted":
            self.identity(params)
            model = string(params.get("toModel"))
            if not model:
                raise protocol_failure()
            self.totals["model"] = model
            reason = string(params.get("reason"))
            self.emit(
                "notice",
                {
                    "code": "model_rerouted",
                    "message": f"codex rerouted the turn to {model}"
                    + (f" ({reason})" if reason is not None else "")
                    + ".",
                },
            )
            self.emit("usage", {"usage": self.usage})
        elif method in ("warning", "deprecationNotice"):
            field = "message" if method == "warning" else "summary"
            if not isinstance(params.get(field), str):
                raise protocol_failure()
            details = string(params.get("details"))
            self.emit(
                "notice",
                {
                    "code": "warning" if method == "warning" else "deprecation",
                    "message": str(params[field]) + ("\n" + details if method != "warning" and details else ""),
                },
            )
        elif method == "error":
            self.identity(params)
            error = object_value(params.get("error"))
            if not isinstance(error.get("message"), str) or not isinstance(params.get("willRetry"), bool):
                raise protocol_failure()
            if params["willRetry"]:
                self.emit("notice", {"code": "retrying", "message": error["message"]})
            else:
                self.error = vendor_failure(error)
        elif method == "turn/completed":
            self.identity(params, turn.get("id"))
            if turn.get("status") not in ("completed", "failed", "interrupted") or self.outcome is not None:
                raise protocol_failure()
            if turn["status"] == "failed" or turn.get("error") is not None or self.error is not None:
                self.outcome = "failed"
                self.error = vendor_failure(turn["error"]) if turn.get("error") else self.error or vendor_failure(None)
            else:
                self.outcome = str(turn["status"])

    def start_call(self, item: Object) -> None:
        id_, type_ = str(item["id"]), str(item["type"])
        if id_ in self.calls or id_ in self.closed:
            raise protocol_failure()
        name, input_ = type_, item
        if type_ == "commandExecution":
            if not isinstance(item.get("command"), str):
                raise protocol_failure()
            name = "shell"
            input_ = {
                "command": plain_command(str(item["command"])),
                **({"cwd": item["cwd"]} if isinstance(item.get("cwd"), str) else {}),
            }
        elif type_ == "collabAgentToolCall":
            if not isinstance(item.get("tool"), str):
                raise protocol_failure()
            name = str(item["tool"])
        elif type_ == "fileChange":
            changes = item.get("changes")
            if not isinstance(changes, list):
                raise protocol_failure()
            normalized: list[Json] = []
            for change in changes:
                if (
                    not isinstance(change, dict)
                    or not isinstance(change.get("path"), str)
                    or not isinstance(change.get("diff"), str)
                    or not isinstance(change.get("kind"), dict)
                    or not isinstance(object_value(change["kind"]).get("type"), str)
                ):
                    raise protocol_failure()
                normalized.append({"path": change["path"], "kind": change["kind"], "content": change["diff"]})
            self.calls[id_] = Call("apply_patch", type_)
            self.output_produced = True
            self.emit("tool_started", {"callId": id_, "name": "apply_patch", "input": normalized})
            return
        self.calls[id_] = Call(name, type_)
        self.output_produced = True
        self.emit("tool_started", {"callId": id_, "name": name, "input": input_})

    def agent_activity(self, item: Object) -> None:
        id_ = string(item.get("agentThreadId"))
        if id_ is None or item.get("kind") not in ("started", "completed"):
            raise protocol_failure()
        if item["kind"] == "started":
            if id_ in self.agents and id_ in self.calls:
                return
            self.closed.discard(id_)
            path = string(item.get("agentPath"))
            self.agents[id_] = Agent(id_, path)
            self.calls[id_] = Call("spawn_agent", "subAgentActivity")
            self.output_produced = True
            self.emit(
                "tool_started",
                {"callId": id_, "name": "spawn_agent", "input": {"path": path} if path is not None else {}},
            )
        elif id_ in self.calls:
            del self.calls[id_]
            self.closed.add(id_)
            agent = self.agents.get(id_)
            if agent is not None and agent.mapper is None:
                agent.active = False
            self.emit(
                "tool_finished",
                {
                    "callId": id_,
                    "ok": True,
                    "result": {"path": agent.path} if agent is not None and agent.path is not None else {},
                },
            )

    def finish_call(self, item: Object) -> None:
        id_ = str(item["id"])
        if id_ in self.closed:
            return
        call = self.calls.get(id_)
        if call is None or call.type != item["type"]:
            raise protocol_failure()
        error: str | None = None
        output_cut = False
        if call.type == "commandExecution":
            if (
                item.get("status") not in ("completed", "failed", "declined")
                or item.get("aggregatedOutput") is not None
                and not isinstance(item["aggregatedOutput"], str)
                or item.get("exitCode") is not None
                and type(item["exitCode"]) is not int
            ):
                raise protocol_failure()
            ok = item["status"] == "completed" and item.get("exitCode") == 0
            result: Json = {
                "output": item["aggregatedOutput"] if isinstance(item.get("aggregatedOutput"), str) else call.output,
                **({"exitCode": item["exitCode"]} if type(item.get("exitCode")) is int else {}),
            }
            output_cut = not isinstance(item.get("aggregatedOutput"), str) and call.output_cut
            if not ok:
                error = (
                    "declined"
                    if item["status"] == "declined"
                    else "failed"
                    if item["status"] == "failed"
                    else f"Command exited with {item.get('exitCode') if item.get('exitCode') is not None else 'an unknown exit code'}."
                )
        else:
            ok = "status" not in item or item["status"] == "completed"
            if item.get("success") is False or item.get("error") or item.get("failure"):
                ok = False
            result = item.get("result") if item.get("result") is not None else item
            if not ok:
                error = string(object_value(item.get("error")).get("message")) or str(item.get("status", "failed"))
        del self.calls[id_]
        self.closed.add(id_)
        self.emit(
            "tool_finished",
            {
                "callId": id_,
                "ok": ok,
                **truncate_result(result),
                **({"truncated": True} if output_cut else {}),
                **({"error": error} if error else {}),
            },
        )
        if call.type == "collabAgentToolCall" and call.name == "spawnAgent":
            if ok:
                receivers = item.get("receiverThreadIds")
                if not isinstance(receivers, list) or any(not isinstance(id_, str) or not id_ for id_ in receivers):
                    raise protocol_failure()
                for receiver in receivers:
                    if receiver != self.thread_id and str(receiver) not in self.agents:
                        self.agents[str(receiver)] = Agent(id_)
            self.replay_foreign()
