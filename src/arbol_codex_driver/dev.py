# Test implementations moved to tests/mid/archived/src/arbol_codex_driver/dev.py.
"""Packaged, explicit no-prompt probes and quota-spending checks."""

import asyncio
import uuid
from pathlib import Path
from typing import cast

from .cancellation import Cancellation, interruptible
from .dev_support import (
    SUBSCRIPTION,
    driver_environment,
    refuse_exhausted,
    stop_child,
    verify,
)
from .errors import Failure
from .json_types import Json, Object, loads, object_value, string
from .runs import Runs
from .state import write_json
from .subscriptions import Subscriptions

SCHEMA_FIELDS = {
    "ThreadStartParams": {
        "cwd",
        "model",
        "approvalPolicy",
        "sandbox",
        "serviceTier",
        "developerInstructions",
        "ephemeral",
        "config",
    },
    "TurnStartParams": {
        "threadId",
        "input",
        "model",
        "effort",
        "summary",
        "approvalPolicy",
        "sandboxPolicy",
        "serviceTier",
    },
    "ThreadResumeParams": {"threadId", "model", "config"},
    "ThreadInjectItemsParams": {"threadId", "items"},
    "ThreadReadParams": {"threadId", "includeTurns"},
    "TurnInterruptParams": {"threadId", "turnId"},
    "ErrorNotification": {"threadId", "turnId", "error", "willRetry"},
    "AccountRateLimitsUpdatedNotification": {"rateLimits"},
    "ThreadTokenUsageUpdatedNotification": {"threadId", "turnId", "tokenUsage"},
    "TurnCompletedNotification": {"threadId", "turn"},
}


def read_schema(directory: Path, name: str) -> Json:
    try:
        return loads((directory / "v2" / (name + ".json")).read_text())
    except (OSError, ValueError):
        raise Failure("tool_unsupported", f"codex did not produce a readable stable {name} schema.") from None


async def probe(
    subscriptions: Subscriptions, inherited: dict[str, str], cancellation: Cancellation
) -> tuple[int, Object]:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


async def check_account(subscriptions: Subscriptions, refresh: bool = True) -> Object:
    account = await subscriptions.require_signed_in(SUBSCRIPTION)
    if account["family"] != "chatgpt":
        raise Failure("invalid_input", "test-chatgpt must belong to the chatgpt family.")
    refuse_exhausted(object_value(account.get("lastUsage")))
    if not refresh:
        return object_value(account.get("lastUsage"))
    usage = await subscriptions.usage(SUBSCRIPTION)
    if usage.get("outcome") != "ok":
        raise Failure("tool_failed", "The test Subscription usage is unavailable; no prompt was sent.")
    refuse_exhausted(usage)
    return usage


def select_model(catalog: Object) -> tuple[str, str | None]:
    values = catalog.get("models", [])
    if catalog.get("source") != "tool" or not isinstance(values, list) or not values:
        raise Failure("tool_failed", "The test Subscription model catalog is unavailable; no prompt was sent.")
    models = [object_value(value) for value in values]
    selected = next(
        (model for model in models if model.get("id") == "gpt-5.6-luna"),
        next(
            (model for model in models if str(model.get("id", "")).endswith("-luna")),
            next((model for model in models if model.get("isDefault") is True), models[0]),
        ),
    )
    model_id = string(selected.get("id"))
    verify(model_id, "codex returned no test model identifier.")
    efforts = selected.get("efforts", [])
    effort = next(
        (
            name
            for name in ("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra")
            if isinstance(efforts, list) and name in efforts
        ),
        string(selected.get("defaultEffort")),
    )
    return cast(str, model_id), effort


async def execute_run(
    subscriptions: Subscriptions,
    env: dict[str, str],
    directory: Path,
    request: Object,
    cancellation: Cancellation,
    stop: bool = False,
) -> tuple[int, list[Object]]:
    """Exercise the same public program from source or a relocated Build."""
    path = directory / (uuid.uuid4().hex + ".json")
    write_json(path, request)
    entry = Path(__file__).resolve().parents[2] / "bin" / "arbol-codex-driver"
    child = await asyncio.create_subprocess_exec(
        str(entry),
        "run",
        "--request",
        str(path),
        "--state-dir",
        str(subscriptions.state.directory),
        *(["--control"] if stop else []),
        env=driver_environment(env),
        cwd=directory,
        start_new_session=True,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        limit=1024 * 1024,
    )
    assert child.stdin is not None and child.stdout is not None and child.stderr is not None
    stderr = asyncio.create_task(child.stderr.read())
    events: list[Object] = []
    sent = False
    if not stop:
        child.stdin.close()

    async def consume() -> None:
        nonlocal sent
        assert child.stdout is not None and child.stdin is not None
        while line := await child.stdout.readline():
            event = object_value(loads(line.decode()))
            events.append(event)
            if stop and event.get("type") == "tool_started" and not sent:
                sent = True
                child.stdin.write(b'{"type":"stop"}\n')
                await child.stdin.drain()
            if event.get("type") == "finished":
                child.stdin.close()
        await child.wait()
        verify(not await stderr, "The development run wrote unexpected diagnostics.")

    failure: BaseException | None = None
    try:
        await interruptible(consume(), cancellation, 90)
    except BaseException as error:
        failure = error
    finally:
        try:
            await stop_child(child)
        except Exception as error:
            failure = failure or error
        finally:
            stderr.cancel()
            await asyncio.gather(stderr, return_exceptions=True)
        try:
            await Runs(subscriptions.state, env).list()
        except Exception as error:
            failure = failure or error
    if failure is not None:
        if isinstance(failure, asyncio.CancelledError):
            raise failure
        # Cleanup is part of the check: a failed cleanup still retains every
        # observed start and usage total from the already accepted turn.
        wrapped = (
            failure
            if isinstance(failure, Failure)
            else Failure("tool_failed", "The development run or its cleanup did not settle within its check bound.")
        )
        wrapped.result["devEvents"] = cast(list[Json], events)
        raise wrapped
    return child.returncode or 0, events


async def live_check(
    build_only: bool, subscriptions: Subscriptions, inherited: dict[str, str], cancellation: Cancellation
) -> tuple[int, Object]:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL

# Archived complete imports; restore needed names in their original scope, not at this file tail.
