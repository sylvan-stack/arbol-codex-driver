import base64
import hashlib
import re
from pathlib import Path
from typing import TypedDict, cast

from .errors import Failure
from .history import images
from .json_types import Object, dumps, now, timestamp, utf8
from .run_request import RunRequest
from .state import State, owner_alive, parse_owner, read_json, write_json


def digest(text: str | bytes) -> str:
    return hashlib.sha256(utf8(text) if isinstance(text, str) else text).hexdigest()


class Fingerprint(TypedDict):
    messages: int
    digest: str


class MessageDigest:
    def __init__(self) -> None:
        self.hash = hashlib.sha256(b"[")
        self.assistant = False
        self.trailing_surrogate = ""
        self.messages = 0

    def separator(self) -> None:
        if self.assistant:
            self.hash.update((dumps(self.trailing_surrogate)[1:-1] + '"]').encode())
            self.trailing_surrogate = ""
            self.assistant = False
        if self.messages:
            self.hash.update(b",")

    def add(self, item: Object) -> None:
        if item.get("type") != "message":
            return
        if item["role"] == "assistant":
            if not self.assistant:
                self.separator()
                self.hash.update(b'["assistant","')
                self.assistant = True
                self.messages += 1
            text = self.trailing_surrogate + str(item["text"])
            self.trailing_surrogate = ""
            if text and 0xD800 <= ord(text[-1]) <= 0xDBFF:
                text, self.trailing_surrogate = text[:-1], text[-1]
            self.hash.update(dumps(text)[1:-1].encode())
        else:
            self.separator()
            self.hash.update(
                dumps(
                    [
                        "user",
                        item["text"],
                        [
                            [picture["mediaType"], digest(base64.b64decode(str(picture["data"])))]
                            for picture in images(item)
                        ],
                    ]
                ).encode()
            )
            self.messages += 1

    def snapshot(self) -> Fingerprint:
        hash_ = self.hash.copy()
        if self.assistant:
            hash_.update((dumps(self.trailing_surrogate)[1:-1] + '"]').encode())
        hash_.update(b"]")
        return {"messages": self.messages, "digest": hash_.hexdigest()}


def message_digest(items: list[Object]) -> Fingerprint:
    stream = MessageDigest()
    for item in items:
        stream.add(item)
    return stream.snapshot()


def saved_conversation(home: Path, conversation: str) -> bool:
    suffix = "-" + conversation + ".jsonl"
    return any(
        path.is_file() and path.name.startswith("rollout-") and path.name.endswith(suffix)
        for directory in (home / "sessions", home / "archived_sessions")
        for path in directory.rglob("*")
        if directory.exists()
    )


class Chats:
    def __init__(self, state: State) -> None:
        self.state = state

    def path(self, subscription_id: str, key: str) -> Path:
        if not re.fullmatch("[a-f0-9]{64}", key):
            raise Failure("invalid_input", "The chat key is not a SHA-256 digest.")
        return self.state.subscription(subscription_id) / "chats" / (key + ".json")

    def entry(self, subscription_id: str, key: str) -> Object | None:
        value = read_json(self.path(subscription_id, key))
        if value is None:
            return None
        if (
            not isinstance(value, dict)
            or not isinstance(value.get("chatSessionId"), str)
            or not value["chatSessionId"]
            or digest(str(value["chatSessionId"])) != key
            or not isinstance(value.get("conversation"), str)
            or not value["conversation"]
            or not isinstance(value.get("workingDirectory"), str)
            or not Path(str(value["workingDirectory"])).is_absolute()
            or type(value.get("messages")) is not int
            or not 0 <= cast(int, value["messages"]) <= 9007199254740991
            or any(
                not isinstance(value.get(field), str) or not re.fullmatch("[a-f0-9]{64}", str(value[field]))
                for field in ("digest", "systemPromptDigest")
            )
            or timestamp(value.get("writtenAt")) is None
        ):
            raise Failure("internal", "Malformed chat map entry.")
        return {
            key: value[key]
            for key in (
                "chatSessionId",
                "conversation",
                "workingDirectory",
                "messages",
                "digest",
                "systemPromptDigest",
                "writtenAt",
            )
        }

    async def select(self, request: RunRequest, home: Path) -> Object:
        if not request.history:
            return {"continuity": "fresh"}

        def rebuilt(reason: str) -> Object:
            return {"continuity": "rebuilt", "rebuildReason": reason}

        if request.chat_session_id is None or request.working_directory is None:
            return rebuilt("no_chat_session")
        entry = self.entry(request.subscription_id, digest(request.chat_session_id))
        if entry is None:
            return rebuilt("first_run")
        fingerprint = message_digest(request.history)
        if entry["messages"] != fingerprint["messages"] or entry["digest"] != fingerprint["digest"]:
            return rebuilt("history_differs")
        if entry["workingDirectory"] != request.working_directory:
            return rebuilt("working_folder_changed")
        if entry["systemPromptDigest"] != digest(request.system_prompt or ""):
            return rebuilt("system_prompt_changed")
        if not saved_conversation(home, str(entry["conversation"])):
            return rebuilt("conversation_gone")
        directory = self.state.directory / "runs"
        for file in directory.glob("*.json"):
            if file.name.startswith("."):
                continue
            record = read_json(file)
            if record is None:
                continue
            if (
                not isinstance(record, dict)
                or not isinstance(record.get("runId"), str)
                or file.name != str(record["runId"]) + ".json"
                or not isinstance(record.get("subscriptionId"), str)
            ):
                raise Failure("internal", "Malformed run record.")
            if (
                record["subscriptionId"] == request.subscription_id
                and record.get("conversation") == entry["conversation"]
                and await owner_alive(parse_owner(record.get("owner")))
            ):
                return rebuilt("in_use")
        return {
            "continuity": "resumed",
            "conversation": entry["conversation"],
            "continuedConversation": entry["conversation"],
        }

    async def settle(
        self, request: RunRequest, plan: Object, conversation: str | None, fingerprint: Fingerprint, completed: bool
    ) -> None:
        if request.chat_session_id is None or request.working_directory is None:
            return
        key = digest(request.chat_session_id)

        async def change() -> None:
            if completed:
                if not conversation:
                    raise Failure("internal", "A completed saved run has no conversation.")
                write_json(
                    self.path(request.subscription_id, key),
                    {
                        "chatSessionId": request.chat_session_id,
                        "conversation": conversation,
                        "workingDirectory": request.working_directory,
                        "messages": fingerprint["messages"],
                        "digest": fingerprint["digest"],
                        "systemPromptDigest": digest(request.system_prompt or ""),
                        "writtenAt": now(),
                    },
                )
            elif "continuedConversation" in plan:
                entry = self.entry(request.subscription_id, key)
                if entry is not None and entry["conversation"] == plan["continuedConversation"]:
                    self.path(request.subscription_id, key).unlink(missing_ok=True)

        await self.state.with_subscription_lock(request.subscription_id, change)
