"""Packaged, explicit no-prompt probes and quota-spending checks."""
import asyncio
import re
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import cast

from arbol_codex_driver.admission import current_session
from arbol_codex_driver.app_server import AppServer
from arbol_codex_driver.cancellation import Cancellation, interruptible
from arbol_codex_driver.dev_support import (
    READY,
    driver_environment,
    probe_shape,
    provenance,
    refuse_exhausted,
    save_report,
    stop_child,
    usage_change,
    verify,
)
from arbol_codex_driver.errors import Failure, safe_failure
from arbol_codex_driver.json_types import Json, Object, loads, now, number, object_value, string
from arbol_codex_driver.runs import Runs
from arbol_codex_driver.state import private_directory, write_json
from arbol_codex_driver.subscriptions import Subscriptions, read_native_account
from arbol_codex_driver.tool import inspect_tool, require_tool


async def probe(
    subscriptions: Subscriptions, inherited: dict[str, str], cancellation: Cancellation
) -> tuple[int, Object]:
    """Observe the installed tool and the native account; start nothing else.

    Codex owns authentication (OG-5). This probe starts no login, logout, thread,
    hook or MCP server and uses no home other than the default native profile.
    The earlier schema, device-login, disposable-home, history and resume
    observations remain dated historical evidence in the Artifact Corpus.
    """
    checks: list[Json] = []
    report: Object = {
        "check": "dev.probe",
        "at": now(),
        "inferenceRequests": 0,
        "provenance": provenance(),
        "checks": checks,
    }
    server: AppServer | None = None
    status = 0
    try:
        tool = await inspect_tool(
            subscriptions.state, string(subscriptions.settings.get("toolPath")), inherited, cancellation
        )
        require_tool(tool)
        report["toolVersion"] = tool["version"]
        server = await subscriptions.start("chatgpt", cancellation=cancellation)
        verify(server.tool_version == tool["version"], "codex changed its handshake version.")
        # One read without a token refresh. Only booleans leave this process.
        account = await read_native_account(server, cancellation)
        checks.append(
            {
                "check": "probe.native-account",
                "outcome": "passed",
                "handshakeVersionMatches": True,
                "signedIn": account is not None,
            }
        )
    except Exception as failure:
        status = 2 if cancellation.aborted else 1
        public = safe_failure(failure)
        report["failureShape"] = probe_shape(public)
        error: Object = {
            "code": public["code"],
            "retryable": public["retryable"],
            "message": public["message"]
            if public["code"] in ("tool_unsupported", "tool_missing")
            else "The Codex probe failed; inspect the failing check and response shapes in its record.",
        }
        if public["code"] in ("tool_unsupported", "tool_missing"):
            # Version refusals are public, bounded facts from inspect_tool and
            # require_tool. Preserve their contract fields while leaving all
            # arbitrary vendor diagnostics only in failureShape.
            version_detail: Object = {
                key: value
                for key, value in object_value(public.get("detail")).items()
                if key == "basis"
                and value == "fields"
                or key in ("neededVersion", "toolVersion")
                and isinstance(value, str)
                and (value == "unknown" or re.fullmatch(r"\d+\.\d+\.\d+", value))
            }
            if version_detail:
                error["detail"] = version_detail
            if public.get("remedy") in ("Install codex.", "Update codex."):
                error["remedy"] = public["remedy"]
        report["error"] = error
        checks.append({"check": "probe.failure", "outcome": "failed"})
    finally:
        try:
            if server is not None:
                await server.end()
        except Exception as failure:
            status = 2 if cancellation.aborted else 1
            report["failureShape"] = probe_shape(safe_failure(failure))
            report["error"] = {
                "code": "tool_failed",
                "retryable": False,
                "message": "The Codex probe could not finish its process cleanup.",
            }
            checks.append({"check": "probe.cleanup", "outcome": "failed"})
    report["outcome"] = "passed" if status == 0 else "cancelled" if status == 2 else "failed"
    return status, save_report(subscriptions.state, report)


async def check_account(subscriptions: Subscriptions, refresh: bool = True, identifier: str = "chatgpt") -> Object:
    # Only the native account is runnable (CDX-1.2); no test or further profile can be selected.
    if identifier != "chatgpt" or identifier not in subscriptions.ids():
        raise Failure("invalid_input", "Select the existing native chatgpt Subscription.")
    account = await subscriptions.require_signed_in(identifier)
    if account["family"] != "chatgpt":
        raise Failure("invalid_input", "The selected existing Subscription must belong to the chatgpt family.")
    refuse_exhausted(object_value(account.get("lastUsage")))
    if not refresh:
        return object_value(account.get("lastUsage"))
    usage = await subscriptions.usage(identifier)
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
    child = await current_session().spawn_helper_async(
        ["run", "--request", str(path), "--state-dir", str(subscriptions.state.directory),
         *(["--control"] if stop else [])],
        entry="bin/entry.py", environment=driver_environment(env), cwd=directory, limit=1024 * 1024,
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
    identifier = inherited.get("ARBOL_BUILD_LIVE_SUBSCRIPTION", "chatgpt")
    checks: list[Json] = []
    report: Object = {
        "check": "dev.build-check" if build_only else "dev.live-check",
        "at": now(),
        "subscriptionId": identifier,
        "turnsAttempted": 0,
        "inferenceRequests": 0,
        "inferenceCountBasis": "observed Driver started events; vendor requests and child turns can exceed this count",
        "spendMayBeIncomplete": False,
        "tokenUsage": {},
        "tokenUsageBasis": "main Driver turns; child token usage is reported separately when available",
        "childTokenUsage": {},
        "checks": checks,
        "provenance": provenance(),
    }
    before: Object = {}
    directory: Path | None = None
    status = 0
    try:
        before = await check_account(subscriptions, identifier=identifier)
        report["usageBefore"] = before
        tool = await inspect_tool(
            subscriptions.state, string(subscriptions.settings.get("toolPath")), inherited, cancellation
        )
        require_tool(tool)
        report["toolVersion"] = tool["version"]
        model, effort = select_model(await subscriptions.models(identifier))
        report.update(model=model, **({"effort": effort} if effort else {}))
        temporary = subscriptions.state.directory / "tmp"
        private_directory(temporary)
        directory = Path(tempfile.mkdtemp(prefix="build-check-" if build_only else "live-check-", dir=temporary))

        async def message(
            name: str,
            prompt: str,
            *,
            tools: bool = False,
            stop: bool = False,
            chat: str | None = None,
            history: list[Json] | None = None,
        ) -> tuple[list[Object], str]:
            assert directory is not None
            await check_account(subscriptions, identifier=identifier)
            cancellation.check()
            request: Object = {
                "subscriptionId": identifier,
                "model": model,
                "tools": "all" if tools else "none",
                "history": history or [],
                "input": {"role": "user", "text": prompt},
                "limits": {"totalSeconds": 60, "idleSeconds": 30},
                **({"effort": effort} if effort else {}),
                **({"workingDirectory": str(directory)} if tools or chat else {}),
                **({"chatSessionId": chat} if chat else {}),
            }
            report["turnsAttempted"] = cast(int, report["turnsAttempted"]) + 1
            events: list[Object] = []
            exit_code: int | None = None
            try:
                exit_code, events = await execute_run(subscriptions, inherited, directory, request, cancellation, stop)
            except Failure as failure:
                partial = failure.result.pop("devEvents", [])
                events = [object_value(item) for item in partial] if isinstance(partial, list) else []
                raise
            finally:
                started = any(event.get("type") == "started" for event in events)
                report["inferenceRequests"] = cast(int, report["inferenceRequests"]) + int(started)
                final = events[-1] if events else {}
                if not started or final.get("type") != "finished":
                    report["spendMayBeIncomplete"] = True
                usage = object_value(
                    final.get(
                        "usage",
                        next(
                            (
                                event.get("usage")
                                for event in reversed(events)
                                if event.get("type") == "usage" and not event.get("parentCallId")
                            ),
                            {},
                        ),
                    )
                )
                aggregate = object_value(report["tokenUsage"])
                for key, value in usage.items():
                    if number(value):
                        aggregate[key] = cast(float, aggregate.get(key, 0)) + cast(float, value)
                    elif key == "model":
                        aggregate[key] = value
                report["tokenUsage"] = aggregate
                child_usage: Object = {}
                for event in events:
                    parent = string(event.get("parentCallId"))
                    if event.get("type") == "usage" and parent is not None:
                        child_usage[parent] = event.get("usage")
                child_aggregate = object_value(report["childTokenUsage"])
                if any(event.get("parentCallId") for event in events) and not child_usage:
                    report["spendMayBeIncomplete"] = True
                for value in child_usage.values():
                    for key, amount in object_value(value).items():
                        if number(amount):
                            child_aggregate[key] = cast(float, child_aggregate.get(key, 0)) + cast(float, amount)
                report["childTokenUsage"] = child_aggregate
                checks.append(
                    {
                        "check": name,
                        "outcome": final.get("outcome", "failed"),
                        "exit": exit_code,
                        "inferenceRequests": int(started),
                        "tokenUsage": usage,
                        "childTokenUsage": list(child_usage.values()),
                        "childTokenUsageReported": bool(child_usage),
                        "eventTypes": [event.get("type") for event in events],
                        "continuity": events[0].get("continuity") if events else None,
                        **({"error": final["error"]} if "error" in final else {}),
                    }
                )
            verify(
                sum(event.get("type") == "finished" for event in events) == 1
                and events[-1].get("outcome") == ("cancelled" if stop else "completed")
                and exit_code == (2 if stop else 0),
                f"The {name} run did not finish as expected.",
            )
            verify(
                [event.get("seq") for event in events] == list(range(1, len(events) + 1)),
                f"The {name} run did not preserve event order.",
            )
            answer = "".join(
                str(event.get("text", ""))
                for event in events
                if event.get("type") == "text" and not event.get("parentCallId")
            )
            return events, answer

        events, answer = await message("live.ready-usage", READY)
        verify(re.search(r"\bready\b", answer, re.I), "The ready check did not produce the expected answer.")
        if not build_only:
            events, answer = await message(
                "live.tools-background",
                "Run printf ready. Explicitly start exactly one sub-agent; "
                "its only task is to run printf ARBOL_CHILD and answer ARBOL_CHILD. Wait for it. "
                "Then start 'sleep 2; printf ARBOL_BACKGROUND' with yield_time_ms 1 and leave it running. "
                "Finish your answer with ready. Do not inspect other files or call MCP servers.",
                tools=True,
            )
            starts = {str(event.get("callId")): event for event in events if event.get("type") == "tool_started"}
            background = {
                call
                for call, event in starts.items()
                if event.get("name") == "shell" and "sleep 2" in str(event.get("input"))
            }
            answer_at = max(
                (
                    index
                    for index, event in enumerate(events)
                    if event.get("type") == "text" and not event.get("parentCallId")
                ),
                default=-1,
            )
            verify(
                any(
                    event.get("type") == "text"
                    and event.get("parentCallId") in starts
                    and "ARBOL_CHILD" in str(event.get("text"))
                    for event in events
                )
                and "ARBOL_CHILD" not in answer
                and re.search(r"\bready\b", answer, re.I)
                and any(
                    index > answer_at
                    and event.get("type") == "tool_finished"
                    and str(event.get("callId")) in background
                    and event.get("ok") is True
                    and "ARBOL_BACKGROUND" in str(event.get("result"))
                    for index, event in enumerate(events)
                ),
                "The tools, child attribution or late background result check did not produce the expected behavior.",
            )
            chat = str(uuid.uuid4())
            prompt = "Remember the word willow. Answer only ready."
            _, first = await message("live.continuity-fresh", prompt, chat=chat)
            history: list[Json] = [
                {"type": "message", "role": "user", "text": prompt},
                {"type": "message", "role": "assistant", "text": first},
            ]
            events, answer = await message(
                "live.continuity-resumed",
                "What word did I give you? Answer only that word.",
                chat=chat,
                history=history,
            )
            verify(
                events[0].get("continuity") == "resumed" and re.search(r"\bwillow\b", answer, re.I),
                "The continuity check did not resume and recall the expected word.",
            )
            await message("live.stopping", "Run sleep 8 then printf ready.", tools=True, stop=True)
    except Exception as failure:
        status = 2 if cancellation.aborted else 1
        report["error"] = safe_failure(failure)
    finally:
        if directory is not None:
            shutil.rmtree(directory, ignore_errors=True)
        # Refresh after failures too: failed attempts can consume quota. Keep an
        # unavailable outcome instead of silently claiming the old usage value.
        if before:
            try:
                after = await subscriptions.usage(identifier)
            except Exception as failure:
                after = {"outcome": "unavailable", "fetchedAt": now(), "windows": [], "error": safe_failure(failure)}
            report.update(usageAfter=after, usageChange=usage_change(before, after))
    report["outcome"] = "passed" if status == 0 else "cancelled" if status == 2 else "failed"
    return status, save_report(subscriptions.state, report)

# Archived complete imports; restore needed names in their original scope, not at this file tail.
