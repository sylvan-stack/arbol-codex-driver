"""Credential-free account fixtures derived from the retained 6 October protocol."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from .errors import Failure
from .event_stream import Output
from .input_stream import Input
from .json_types import Json, dumps, loads

type Record = dict[str, Any]
VERSION = "0.159.2"
SOURCE = "~/Artifacts/arbol-codex-driver/research/probe-scripts-2026-10-06/live/codex-all.json"
ACCOUNT: Record = {"type": "chatgpt", "email": "fixture@example.invalid", "planType": "fixture"}
SUBSCRIPTION_SCENARIOS = {"C1", "C2", "C4", "C5", "C6", "C7", "C8", "C39", "C40", "C41"}
SUBSCRIPTION_PARTS = {
    "supported",
    "success",
    "by-code",
    "waiting",
    "rejected",
    "unavailable",
    "failed",
    "wrong-home",
    "other-account",
    "unknown-windows",
}
RUN_SCENARIOS = {
    "C5",
    "C7",
    "C8",
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
    "C26",
    "C27",
    "C28",
    "C29",
    "C30",
    "C32",
    "C33",
    "C35",
    "C36",
    "C37",
    "C38",
    "C42",
    "C43",
}
CONFIG: Record = {
    "check_for_update_on_startup": False,
    "web_search": "live",
    "cli_auth_credentials_store": "file",
    "analytics": {"enabled": False},
    "features": {"memories": False},
}


def fixture_models(*, descriptions: bool = False) -> list[Record]:
    result: list[Record] = []
    for index, id_ in enumerate(("gpt-6.1-sol", "gpt-6-astra")):
        model: Record = {
            "id": id_,
            "model": id_,
            "displayName": "GPT-6.1-Sol" if index == 0 else "GPT-6-Astra",
            "hidden": False,
            "supportedReasoningEfforts": [
                {"reasoningEffort": effort, "description": "Fixture effort"}
                for effort in ("low", "medium", "high", "xhigh", "max", "ultra")
            ],
            "defaultReasoningEffort": "low" if index == 0 else "medium",
            "serviceTiers": [
                {
                    "id": "priority",
                    "name": "Fast",
                    "description": "2x speed, increased usage" if descriptions else "Fixture priority tier",
                }
            ],
            "isDefault": index == 0,
        }
        if descriptions:
            model["description"] = (
                "Latest workhorse model for coding and everyday work."
                if index == 0
                else "Frontier intelligence for the most demanding work."
            )
        result.append(model)
    return result


def environment_checks(home: str | None) -> Record:
    try:
        private = home is not None and Path(home).stat().st_mode & 0o077 == 0
    except OSError:
        private = False
    return {
        "home": home,
        "privateHome": private,
        "source": SOURCE,
        "injectedVariablesAbsent": all(
            not name.startswith("OPENAI_")
            and (not name.startswith("CODEX_") or name == "CODEX_HOME")
            and name not in {"ANTHROPIC_API_KEY", "CLAUDECODE", "CLAUDE_SESSION_ID", "NODE_OPTIONS"}
            for name in os.environ
        ),
    }


def append_record(folder: Path, value: Record) -> None:
    fd = os.open(folder / "received.jsonl", os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(dumps(value) + "\n")


def operation(method: object) -> str:
    return {
        "account/rateLimits/read": "usage",
        "model/list": "models",
        "account/read": "check",
        "account/login/start": "sign-in",
        "account/logout": "sign-out",
        "account/login/cancel": "cancel-sign-in",
        "initialize": "setup",
        "initialized": "setup",
        "config/read": "setup",
    }.get(str(method), "unsupported")


async def stand_in(folder: Path, args: list[str], output: Output) -> int:
    words = (folder / "scenario").read_text().strip().split()
    scenario, part = words[0] if words else "", words[1] if len(words) > 1 else "supported"
    if (
        scenario in RUN_SCENARIOS
        and not (scenario == "C5" and part in SUBSCRIPTION_PARTS)
        and not (scenario == "C7" and part in SUBSCRIPTION_PARTS and part != "failed")
        and not (scenario == "C32" and part == "info")
        or scenario == "C40" and part not in SUBSCRIPTION_PARTS
        or scenario == "C4" and part == "success"
    ):
        from .run_stand_in import run_stand_in

        return await run_stand_in(folder, args, output)
    subscriptions = scenario in SUBSCRIPTION_SCENARIOS
    if len(words) > 2 or not (
        scenario == "C31"
        and part in {"supported", "old", "missing"}
        or scenario == "C3"
        and part == "supported"
        or scenario == "C32"
        and part == "info"
        or subscriptions
        and part in SUBSCRIPTION_PARTS
    ):
        raise Failure("invalid_input", "This stand-in does not implement that scenario.")
    version = None if part == "missing" else "0.159.1" if part == "old" else VERSION
    home = os.environ.get("CODEX_HOME")
    credential = Path(home) / "auth.json" if home else None
    logged_in = credential is not None and credential.is_file()
    checks = (
        {
            **environment_checks(home),
            "synthetic": "Successful login, account data, cursor, limit-window and failure variants of the recorded protocol",
            "hasCredential": logged_in,
        }
        if subscriptions
        else {}
    )
    record: Record = {
        "scenario": scenario,
        "part": part,
        "arguments": args,
        "environment": sorted(os.environ),
        "workingDirectory": os.getcwd(),
        "toolVersion": version,
        "checks": checks,
    }
    append_record(folder, record)
    if version is None:
        return 127
    if args == ["--version"]:
        await output.write(f"codex-cli {version}\n")
        return 0
    if args != ["app-server"]:
        raise Failure("unsupported", "This stand-in implements only the version probe and app-server.")
    input_ = Input()
    await input_.open()
    initialized = False
    login_id: str | None = None
    completion: asyncio.Task[None] | None = None
    write_lock = asyncio.Lock()

    async def write(value: Json) -> None:
        async with write_lock:
            await output.write(dumps(value) + "\n")

    async def notify(method: str, params: Json) -> None:
        await write({"method": method, "params": params})

    async def complete_login() -> None:
        nonlocal login_id, logged_in
        await asyncio.sleep(0.075)
        current = login_id
        if current is None or credential is None:
            return
        if part != "failed":
            fd = os.open(credential, os.O_WRONLY | os.O_TRUNC | os.O_CREAT, 0o600)
            with os.fdopen(fd, "w") as stream:
                stream.write(dumps({"credential": "fixture-vendor-secret"}))
            logged_in = True
        login_id = None
        await notify(
            "account/login/completed",
            {
                "loginId": current,
                "success": part != "failed",
                "error": "Login server error: Login cancelled" if part == "failed" else None,
                "onboardingEntrypoint": None,
            },
        )
        if part != "failed":
            await notify("account/updated", {"authMode": "chatgpt", "planType": ACCOUNT["planType"]})

    try:
        while (line := await input_.line()) is not None:
            parsed_request = loads(line)
            if not isinstance(parsed_request, dict):
                continue
            request: Record = parsed_request
            if subscriptions:
                append_record(
                    folder,
                    {
                        **record,
                        "stage": "request",
                        "request": request,
                        "checks": {**checks, "operation": operation(request.get("method"))},
                    },
                )
            if "id" not in request:
                continue

            async def answer(result: Json, id_: Json = request["id"]) -> None:
                await write({"id": id_, "result": result})

            async def error(message: str, code: int = -32600, id_: Json = request["id"]) -> None:
                await write({"id": id_, "error": {"code": code, "message": message}})

            method = request.get("method")
            params = request.get("params") if isinstance(request.get("params"), dict) else {}
            assert isinstance(params, dict)
            if method == "initialize" and not initialized:
                initialized = True
                await answer(
                    {
                        "userAgent": f"arbol-codex-driver/{version} (Mac OS 27.0.1; arm64) unknown (arbol-codex-driver; 1.0.0)",
                        "codexHome": str(folder / "wrong-home")
                        if part == "wrong-home"
                        else home or os.environ.get("HOME"),
                        "platformFamily": "unix",
                        "platformOs": "macos",
                    }
                )
            elif not initialized:
                await error("Not initialized")
            elif not subscriptions or home is None or credential is None:
                await error("This stand-in implements only initialize.")
            elif method == "config/read":
                await answer({"config": CONFIG, "origins": {}, "layers": None})
            elif method == "account/login/start":
                if params.get("type") not in ("chatgpt", "chatgptDeviceCode"):
                    await error("Unsupported login type", -32602)
                    continue
                if login_id:
                    await notify(
                        "account/login/completed",
                        {
                            "loginId": login_id,
                            "success": False,
                            "error": "Login server error: Login cancelled",
                            "onboardingEntrypoint": None,
                        },
                    )
                    if completion is not None:
                        completion.cancel()
                login_id = f"fixture-login-{os.getpid()}"
                await answer(
                    {
                        "type": "chatgptDeviceCode",
                        "loginId": login_id,
                        "verificationUrl": "https://auth.openai.com/codex/device",
                        "userCode": "FIXT-12345",
                    }
                    if params["type"] == "chatgptDeviceCode"
                    else {
                        "type": "chatgpt",
                        "loginId": login_id,
                        "authUrl": f"https://auth.openai.com/oauth/authorize?redirect_uri=http%3A%2F%2F127.0.0.1%3A1455%2Fauth%2Fcallback&state={login_id}",
                    }
                )
                if part != "waiting":
                    completion = asyncio.create_task(complete_login())
            elif method == "account/login/cancel":
                current = login_id
                if current is None or params.get("loginId") != current:
                    await answer({"status": "notFound"})
                    continue
                if completion is not None:
                    completion.cancel()
                login_id = None
                await answer({"status": "canceled"})
                await notify(
                    "account/login/completed",
                    {
                        "loginId": current,
                        "success": False,
                        "error": "Login server error: Login was not completed",
                        "onboardingEntrypoint": None,
                    },
                )
            elif method == "account/read":
                if part == "unavailable":
                    await error("Fixture account service unavailable", -32000)
                else:
                    await answer(
                        {
                            "account": ({"type": "apiKey"} if part == "other-account" else ACCOUNT)
                            if logged_in and part != "rejected"
                            else None,
                            "requiresOpenaiAuth": True,
                            "workspaceRouting": {
                                "chatgptAccountId": "00000000-0000-0000-0000-000000000000",
                                "backendOrigin": "https://chatgpt.com",
                                "accountRoutingOverride": "NO_CONSTRAINT",
                            },
                        }
                    )
            elif method == "account/logout":
                credential.unlink(missing_ok=True)
                logged_in = False
                await answer({})
                await notify("account/updated", {"authMode": None, "planType": None})
            elif method == "account/rateLimits/read":
                if part == "rejected":
                    await error("Authentication failed: ChatGPT login expired; please log in again.", -32000)
                elif part == "unavailable":
                    await error("Fixture usage service temporarily unavailable", -32000)
                else:
                    limits: Record = {
                        "limitId": "codex",
                        "limitName": None,
                        "normalModelSlug": None,
                        "primary": {"usedPercent": 7, "windowDurationMins": None, "resetsAt": None}
                        if part == "unknown-windows"
                        else {"usedPercent": 25, "windowDurationMins": 10080, "resetsAt": 1791640848},
                        "secondary": {
                            "usedPercent": 100,
                            "windowDurationMins": 1440 if part == "unknown-windows" else 300,
                            "resetsAt": None,
                        },
                        "credits": {"hasCredits": False, "unlimited": False, "balance": "0"},
                        "individualLimit": None,
                        "spendControlReached": False,
                        "planType": "fixture",
                        "rateLimitReachedType": None,
                    }
                    await answer(
                        {
                            "ordinaryUsageAllowed": True,
                            "rateLimits": limits,
                            "rateLimitsByLimitId": {"codex": limits},
                            "rateLimitResetCredits": {"availableCount": 0, "credits": []},
                            "accountId": "00000000-0000-0000-0000-000000000000",
                            "rateLimitUpsell": None,
                        }
                    )
            elif method == "model/list":
                if part == "unavailable":
                    await error("Fixture model service temporarily unavailable", -32000)
                elif params.get("includeHidden") is not False:
                    await error("The fixture requires hidden models to be excluded", -32602)
                elif params.get("cursor") is None:
                    await answer({"data": [fixture_models(descriptions=True)[0]], "nextCursor": "fixture-page-2"})
                elif params.get("cursor") == "fixture-page-2":
                    await answer({"data": [fixture_models(descriptions=True)[1]], "nextCursor": None})
                else:
                    await error("Unknown model cursor", -32602)
            else:
                await error("This stand-in implements only Subscription app-server requests.", -32601)
    finally:
        input_.close()
        if completion is not None:
            completion.cancel()
            await asyncio.gather(completion, return_exceptions=True)
    return 0
