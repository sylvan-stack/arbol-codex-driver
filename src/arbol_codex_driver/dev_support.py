"""Standard-library helpers shared by the packaged development checks."""

import asyncio
import hashlib
import os
import platform
import signal
import sys
import time
from pathlib import Path
from typing import cast

from .build import build_identity
from .cancellation import Cancellation, interruptible
from .environment import clean_environment
from .errors import Failure
from .json_types import Json, Object, number, object_value
from .process_groups import collect_process_groups, force_process_groups
from .state import Owner, State, process_owner, write_json
from .tool import ChildTransport

SUBSCRIPTION = "test-chatgpt"
READY = "Answer with the single word: ready"
ENUMS = {
    "type": {
        "chatgpt",
        "chatgptDeviceCode",
        "apiKey",
        "message",
        "function_call",
        "function_call_output",
        "input_text",
        "output_text",
        "input_image",
        "readOnly",
        "dangerFullAccess",
        "idle",
        "error",
    },
    "status": {"completed", "inProgress", "failed", "interrupted", "declined", "idle", "starting", "ready"},
    "authStatus": {"notLoggedIn", "bearerToken", "oAuth"},
    "approvalPolicy": {"never", "on-request", "untrusted", "on-failure"},
    "sandbox": {"read-only", "danger-full-access", "workspace-write"},
    "reasoningEffort": {"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"},
    "defaultReasoningEffort": {"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"},
    "multiAgentMode": {"explicitRequestOnly"},
}


def probe_shape(value: Json, key: str = "") -> Json:
    """Retain field names and bounded protocol enums, never account/model values."""
    if isinstance(value, dict):
        return {name: probe_shape(item, name) for name, item in value.items()}
    if isinstance(value, list):
        return [probe_shape(item, key) for item in value]
    if isinstance(value, str):
        return value if value in ENUMS.get(key, set()) else "string"
    return None if value is None else "boolean" if isinstance(value, bool) else "number"


def verify(condition: object, message: str) -> None:
    if not condition:
        raise Failure("tool_unsupported", message)


def schema_enums(value: Json) -> set[str]:
    if isinstance(value, list):
        return set().union(*(schema_enums(item) for item in value))
    if not isinstance(value, dict):
        return set()
    values = value.get("enum", [])
    result = {item for item in values if isinstance(item, str)} if isinstance(values, list) else set()
    return result.union(*(schema_enums(item) for item in value.values()))


def provenance() -> Object:
    directory = Path(__file__).resolve().parent
    hashes: Object = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(directory.glob("*.py"))
    }
    return {
        "driver": "codex",
        **build_identity(),
        "runtime": {
            "implementation": platform.python_implementation(),
            "version": platform.python_version(),
            "platform": sys.platform,
            "machine": platform.machine(),
        },
        "source": {"moduleSha256": hashes},
    }


def save_report(state: State, report: Object) -> Object:
    name = str(report["check"]).removeprefix("dev.") + "-" + str(report["at"]).replace(":", "-") + ".json"
    path = state.directory / "research" / name
    result = {**report, "reportPath": str(path)}
    write_json(path, result)
    return result


def refuse_exhausted(report: Object) -> None:
    windows = report.get("windows", [])
    if not isinstance(windows, list):
        raise Failure("tool_failed", "The test Subscription returned an unreadable usage report; no prompt was sent.")
    for value in windows:
        window = object_value(value)
        percent = window.get("usedPercent")
        if window.get("limitReached") is True or number(percent) and cast(float, percent) >= 100:
            raise Failure(
                "rate_limited", "The test Subscription has a usage window used up. Wait before running the check."
            )
    extra = object_value(report.get("extra"))
    if extra.get("ordinaryUsageAllowed") is False or extra.get("spendControlReached") is True:
        raise Failure(
            "rate_limited", "The test Subscription does not allow ordinary usage. Wait before running the check."
        )
    # Some vendor replies list additional model-specific windows only by limit id.
    for limits in object_value(extra.get("rateLimitsByLimitId")).values():
        for key in ("primary", "secondary"):
            window = object_value(object_value(limits).get(key))
            percent = window.get("usedPercent")
            if number(percent) and cast(float, percent) >= 100:
                raise Failure(
                    "rate_limited", "The test Subscription has a usage window used up. Wait before running the check."
                )


def usage_change(before: Object, after: Object) -> list[Json]:
    prior = before.get("windows", [])
    current = after.get("windows", [])
    if not isinstance(prior, list) or not isinstance(current, list):
        return []
    changes: list[Json] = []
    for value in current:
        window = object_value(value)
        previous = next(
            (
                object_value(item)
                for item in prior
                if object_value(item).get("kind") == window.get("kind")
                and object_value(item).get("label") == window.get("label")
            ),
            {},
        )
        old, new = previous.get("usedPercent"), window.get("usedPercent")
        changes.append(
            {
                "kind": window.get("kind"),
                "label": window.get("label"),
                **({"beforePercent": old} if number(old) else {}),
                **({"afterPercent": new} if number(new) else {}),
                **(
                    {"changePercent": round(cast(float, new) - cast(float, old), 3)}
                    if number(old) and number(new)
                    else {}
                ),
            }
        )
    return changes


async def command(
    program: str, arguments: list[str], env: dict[str, str], cwd: Path, cancellation: Cancellation, timeout: float = 30
) -> tuple[int, bytes]:
    """Bound a no-prompt subprocess and reap its process groups and pipes."""
    cancellation.check()
    child = await asyncio.create_subprocess_exec(
        program,
        *arguments,
        cwd=cwd,
        env=env,
        start_new_session=True,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    owner: Owner | None = None
    assert child.stdout is not None

    async def read() -> bytes:
        assert child.stdout is not None
        result = bytearray()
        while chunk := await child.stdout.read(65536):
            result.extend(chunk)
            if len(result) > 4 * 1024 * 1024:
                raise Failure("tool_failed", "The probe command returned oversized output.")
        await child.wait()
        return bytes(result)

    try:
        owner = await process_owner(child.pid)
        output = await interruptible(read(), cancellation, timeout)
        return child.returncode or 0, output
    finally:
        try:
            if owner is not None:
                await force_process_groups(await collect_process_groups(owner), time.monotonic() + 1)
        finally:
            # A live child has not released its PID; its new-session group can
            # be ended even if the system's process-identity query failed.
            if child.returncode is None:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            try:
                await asyncio.wait_for(child.wait(), 1)
            finally:
                cast(ChildTransport, child)._transport.close()


def driver_environment(inherited: dict[str, str]) -> dict[str, str]:
    env = clean_environment(inherited, inherited.get("HOME") or str(Path.home()))
    if "ARBOL_TEST_TIME_SCALE" in inherited:
        env["ARBOL_TEST_TIME_SCALE"] = inherited["ARBOL_TEST_TIME_SCALE"]
    return env


async def stop_child(child: asyncio.subprocess.Process) -> None:
    try:
        if child.returncode is None:
            child.send_signal(signal.SIGTERM)
            try:
                await asyncio.wait_for(child.wait(), 20)
            except TimeoutError:
                owner = await process_owner(child.pid)
                if owner is not None:
                    await force_process_groups(await collect_process_groups(owner), time.monotonic() + 1)
    finally:
        if child.returncode is None:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        try:
            await asyncio.wait_for(child.wait(), 1)
        finally:
            cast(ChildTransport, child)._transport.close()
