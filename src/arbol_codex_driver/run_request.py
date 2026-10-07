import os
import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from .arguments import Options
from .errors import Failure
from .json_types import Json, Object, loads, number, object_value, string


@dataclass
class RunRequest:
    run_id: str
    subscription_id: str
    history: list[Object]
    input: Object
    tools: str
    model: str | None = None
    effort: str | None = None
    effort_from_settings: bool = False
    service_tier: str | None = None
    system_prompt: str | None = None
    working_directory: str | None = None
    additional_directories: list[str] = field(default_factory=list)
    search_path: list[str] = field(default_factory=list)
    chat_session_id: str | None = None
    limits: Object | None = None
    labels: Object | None = None
    control: bool = False
    output: str = "events"


async def read_run_request(
    options: Options,
    *,
    settings: Object | None = None,
    message: str | None = None,
    first_line: Callable[[], Awaitable[str]] | None = None,
    identity: Callable[[str, Object | None], None] | None = None,
) -> RunRequest:
    def bad(text: str) -> None:
        raise Failure("invalid_input", text)

    def option(name: str) -> str | None:
        value = options.get(name)
        if value is None:
            return None
        if not isinstance(value, str) or not value:
            bad(f"Option --{name} needs a value.")
        return cast(str, value)

    def repeat(name: str) -> list[str]:
        value = options.get(name, [])
        values = [value] if isinstance(value, str) else value
        if not isinstance(values, list) or any(not isinstance(item, str) or not item for item in values):
            bad(f"Option --{name} needs a value.")
        return cast(list[str], values)

    value: Object = {}
    file = option("request")
    if file is not None:
        try:
            if file == "-" and first_line is None:
                bad("The request line is missing.")
            parsed = loads(
                await cast(Callable[[], Awaitable[str]], first_line)() if file == "-" else Path(file).read_text()
            )
        except (OSError, ValueError, Failure):
            bad("The request could not be read as JSON.")
            raise AssertionError from None
        if not isinstance(parsed, dict):
            bad("The request must be a JSON object.")
        value = object_value(parsed).copy()
    for name, key in {
        "subscription": "subscriptionId",
        "model": "model",
        "effort": "effort",
        "service-tier": "serviceTier",
        "cwd": "workingDirectory",
        "tools": "tools",
        "chat-session": "chatSessionId",
        "run-id": "runId",
    }.items():
        replacement = option(name)
        if replacement is not None:
            value[key] = replacement
    prompt_file = option("system-prompt-file")
    if prompt_file is not None:
        try:
            value["systemPrompt"] = Path(prompt_file).read_text()
        except OSError:
            bad("The system prompt file could not be read.")
    if message is not None:
        value["input"] = {**object_value(value.get("input")), "role": "user", "text": message}
    if "add-dir" in options:
        value["additionalDirectories"] = [item for item in repeat("add-dir")]
    if "label" in options:
        label_values = object_value(value.get("labels")).copy()
        for label in repeat("label"):
            key, equal, content = label.partition("=")
            if not key or not equal:
                bad("A label must be key=value.")
            label_values[key] = content
        value["labels"] = label_values
    for key in ("runId", "subscriptionId", "model", "effort", "serviceTier", "workingDirectory", "chatSessionId"):
        if key in value and (not isinstance(value[key], str) or not value[key]):
            bad(f"Invalid request field {key}.")
    if "systemPrompt" in value and not isinstance(value["systemPrompt"], str):
        bad("Invalid systemPrompt.")
    settings = settings or {}
    subscription_id = string(value.get("subscriptionId")) or string(settings.get("defaultSubscription")) or "chatgpt"
    defaults = object_value(object_value(settings.get("subscriptions")).get(subscription_id))
    run_id = string(value.get("runId")) or str(uuid.uuid4())
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}", run_id):
        bad("The run identifier is not a safe file name.")
    if "labels" in value and (
        not isinstance(value["labels"], dict)
        or any(not isinstance(item, str) for item in object_value(value["labels"]).values())
    ):
        bad("Labels must be a string mapping.")
    labels = cast(Object | None, value.get("labels"))
    if identity is not None:
        identity(run_id, labels)
    tools = value.get("tools", "none" if file is None else None)
    if tools not in ("all", "none"):
        bad("The request must name tools as all or none.")
    history = value.get("history", [] if file is None else None)
    if not isinstance(history, list):
        bad("The request must contain a history array.")

    def valid_images(images: Json) -> bool:
        return isinstance(images, list) and all(
            isinstance(picture, dict)
            and picture.get("mediaType") in ("image/png", "image/jpeg", "image/webp", "image/gif")
            and isinstance(picture.get("data"), str)
            and len(str(picture["data"])) > 0
            and len(str(picture["data"])) % 4 == 0
            and re.fullmatch(r"[A-Za-z0-9+/]*={0,2}", str(picture["data"])) is not None
            for picture in images
        )

    assert isinstance(history, list)
    for item in history:
        if not isinstance(item, dict):
            bad("Each history item must be an object.")
        assert isinstance(item, dict)
        if item.get("type") == "message":
            if (
                item.get("role") not in ("user", "assistant")
                or not isinstance(item.get("text"), str)
                or not valid_images(item.get("images", []))
            ):
                bad("Invalid history message.")
        elif item.get("type") == "tool_call":
            if (
                not isinstance(item.get("name"), str)
                or not item["name"]
                or "input" not in item
                or type(item.get("ok")) is not bool
                or "error" in item
                and not isinstance(item["error"], str)
            ):
                bad("Invalid history tool call.")
            if item["name"] == "shell" and (
                not isinstance(item["input"], dict) or not isinstance(object_value(item["input"]).get("command"), str)
            ):
                bad("A shell history call needs a command.")
        else:
            bad("Unknown history item type.")
    input_ = value.get("input")
    if not isinstance(input_, dict) or input_.get("role") != "user" or not isinstance(input_.get("text"), str):
        bad("The input must be a user message with text.")
    assert isinstance(input_, dict)
    if not valid_images(input_.get("images", [])):
        bad("Images must have supported media types and base64 data.")

    def paths(key: str) -> list[str]:
        values = value.get(key, [])
        if not isinstance(values, list) or any(not isinstance(item, str) or not os.path.isabs(item) for item in values):
            bad(f"{key} must contain absolute paths.")
        return cast(list[str], values)

    additional = paths("additionalDirectories")
    search = paths("searchPath")
    work = string(value.get("workingDirectory"))
    if work is None and tools == "all":
        bad("A run with tools needs a working directory.")
    if any(
        not Path(directory).is_absolute() or not Path(directory).is_dir()
        for directory in [*([work] if work is not None else []), *additional]
    ):
        bad("A working or additional directory does not exist.")
    if work is not None:
        work = str(Path(work).resolve(strict=True))
    if "limits" in value and (
        not isinstance(value["limits"], dict)
        or any(
            key not in ("idleSeconds", "totalSeconds") or not number(limit) or cast(float, limit) < 0
            for key, limit in object_value(value["limits"]).items()
        )
    ):
        bad("Invalid run limits.")
    if "control" in options and not isinstance(options["control"], bool):
        bad("Option --control takes no value.")
    output = option("output") or "events"
    if output not in ("events", "text"):
        bad("Output must be events or text.")
    return RunRequest(
        run_id,
        subscription_id,
        cast(list[Object], history),
        input_,
        str(tools),
        string(value.get("model")) or string(defaults.get("defaultModel")),
        string(value.get("effort")) or string(defaults.get("defaultEffort")),
        "effort" not in value and "defaultEffort" in defaults,
        string(value.get("serviceTier")),
        string(value.get("systemPrompt")),
        work,
        additional,
        search,
        string(value.get("chatSessionId")),
        cast(Object | None, value.get("limits")),
        labels,
        options.get("control") is True,
        output,
    )
