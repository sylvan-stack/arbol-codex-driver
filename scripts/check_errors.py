"""Opt-in SYL-91 unreachable-vendor probe and one tiny usage-report check.

The proxy probe cannot reach the vendor. Live mode first reads test-chatgpt's
usage and checks whether the vendor still allows ordinary use or has credits.
Neither mode reads credentials, changes login, or uses another Subscription.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import socket
import sys
import tempfile
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from arbol_codex_driver.json_types import object_value, timestamp  # noqa: E402

STATE = Path.home() / "Library/Application Support/Arbol/drivers/arbol-codex-driver"
ENTRY = ROOT / "bin/arbol-codex-driver"
SUBSCRIPTION = "test-chatgpt"


def clean_env() -> dict[str, str]:
    return {"HOME": str(Path.home()), "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
            "LANG": "en_US.UTF-8", "TMPDIR": tempfile.gettempdir()}


async def command(arguments: list[str], env: dict[str, str], seconds: float = 90) -> tuple[int, bytes, bytes]:
    child = await asyncio.create_subprocess_exec(str(ENTRY), *arguments, "--state-dir", str(STATE), env=env,
                                                 stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        async with asyncio.timeout(seconds):
            output, error = await child.communicate()
    except TimeoutError:
        child.terminate()
        try:
            await asyncio.wait_for(child.wait(), 20)
        except TimeoutError:
            child.kill()
            await child.wait()
        raise ValueError("The explicit vendor-check deadline was reached.") from None
    return child.returncode or 0, output, error


async def usage(env: dict[str, str]) -> dict[str, Any]:
    code, output, error = await command(["subscriptions", "usage", SUBSCRIPTION], env)
    report = json.loads(output)
    if code or error or not isinstance(report, dict) or report.get("outcome") != "ok":
        raise ValueError("test-chatgpt did not return an available usage report; no live prompt was sent.")
    return report


def shares(report: dict[str, Any]) -> list[dict[str, Any]]:
    return [{key: window[key] for key in ("kind", "windowMinutes", "usedPercent", "resetsAt", "limitReached")
             if key in window} for window in report.get("windows", [])]


def usage_change(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    changes = []
    for window in after.get("windows", []):
        previous: dict[str, Any] = next((item for item in before.get("windows", [])
                                        if item.get("windowMinutes") == window.get("windowMinutes")
                                        and item.get("kind") == window.get("kind")), {})
        old, new = previous.get("usedPercent"), window.get("usedPercent")
        if isinstance(old, (int, float)) and isinstance(new, (int, float)):
            changes.append({"kind": window.get("kind"), "windowMinutes": window.get("windowMinutes"),
                            "percentagePointChange": new - old})
    return changes


async def execute_run(env: dict[str, str], total: float, idle: float) -> dict[str, Any]:
    run_id = "syl91-check-" + uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix="syl91-check-") as name:
        request = Path(name) / "request.json"
        request.write_text(json.dumps({"subscriptionId": SUBSCRIPTION, "runId": run_id,
                                       "model": "gpt-5.6-luna", "effort": "low", "tools": "none", "history": [],
                                       "limits": {"idleSeconds": idle, "totalSeconds": total},
                                       "input": {"role": "user", "text": "Reply exactly OK."}}))
        began = time.monotonic()
        code, output, error = await command(["run", "--request", str(request)], env, total + 30)
        events = [json.loads(line) for line in output.splitlines()]
        return {"runId": run_id, "exitCode": code, "seconds": round(time.monotonic() - began, 3),
                "quietStderr": not error, "events": events,
                "scratchRemoved": not (STATE / "tmp" / run_id).exists(),
                "runRecordRemoved": not (STATE / "runs" / (run_id + ".json")).exists()}


async def probe() -> dict[str, Any]:
    # Refuse if the chosen proxy port is unexpectedly serving connections.
    with socket.socket() as connection:
        connection.settimeout(1)
        if connection.connect_ex(("127.0.0.1", 9)) == 0:
            raise ValueError("The probe proxy port is listening; no probe prompt was sent.")
    env = clean_env()
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        env[key] = "http://127.0.0.1:9"
    env.update(NO_PROXY="", no_proxy="")
    run_id = "syl91-check-" + uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix="syl91-proxy-") as name:
        request = Path(name) / "request.json"
        request.write_text(json.dumps({"subscriptionId": SUBSCRIPTION, "runId": run_id,
                                       "model": "gpt-5.6-luna", "effort": "low", "tools": "none", "history": [],
                                       "limits": {"idleSeconds": 0, "totalSeconds": 60},
                                       "input": {"role": "user", "text": "Reply exactly OK."}}))
        child = await asyncio.create_subprocess_exec(str(ENTRY), "run", "--request", str(request), "--control",
                                                     "--state-dir", str(STATE), env=env, stdin=asyncio.subprocess.PIPE,
                                                     stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        assert child.stdout is not None and child.stdin is not None
        events: list[dict[str, Any]] = []
        began = time.monotonic()
        deadline = began + 15
        while child.returncode is None and time.monotonic() < deadline:
            try:
                line = await asyncio.wait_for(child.stdout.readline(), max(0.001, deadline - time.monotonic()))
            except TimeoutError:
                break
            if not line:
                break
            events.append(json.loads(line))
            if sum(event.get("type") == "notice" and event.get("code") == "retrying" for event in events) >= 2:
                break
        waiting = child.returncode is None and not any(event.get("type") == "finished" for event in events)
        stop_at = round(time.monotonic() - began, 3)
        if child.returncode is None:
            child.stdin.write(b'{"type":"stop"}\n')
            await child.stdin.drain()
        forced = False
        try:
            output, error = await asyncio.wait_for(child.communicate(), 20)
        except TimeoutError:
            forced = True
            child.terminate()
            try:
                output, error = await asyncio.wait_for(child.communicate(), 20)
            except TimeoutError:
                child.kill()
                output, error = await child.communicate()
        events.extend(json.loads(line) for line in output.splitlines())
        result: dict[str, Any] = {
            "runId": run_id, "exitCode": child.returncode, "seconds": round(time.monotonic() - began, 3),
            "stopAtSeconds": stop_at, "waitingBeforeStop": waiting, "forcedTermination": forced,
            "quietStderr": not error, "events": events,
            "scratchRemoved": not (STATE / "tmp" / run_id).exists(),
            "runRecordRemoved": not (STATE / "runs" / (run_id + ".json")).exists(),
        }
    events = result["events"]
    final = events[-1] if events else {}
    checks = {
        "started": any(event.get("type") == "started" for event in events),
        "retryNotices": sum(event.get("type") == "notice" and event.get("code") == "retrying" for event in events) >= 2,
        "waitingBeforeStop": result["waitingBeforeStop"],
        "callerStopCancelled": final.get("type") == "finished" and final.get("outcome") == "cancelled",
        "noForcedTermination": not result["forcedTermination"],
        "oneFinished": sum(event.get("type") == "finished" for event in events) == 1,
        "orderedEvents": [event.get("seq") for event in events] == list(range(1, len(events) + 1)),
        "quietStderr": result["quietStderr"], "scratchRemoved": result["scratchRemoved"],
        "runRecordRemoved": result["runRecordRemoved"],
    }
    return {"check": "probe.errors", "subscriptionId": SUBSCRIPTION,
            "proxy": "http://127.0.0.1:9", "inferenceAttempts": int(checks["started"]),
            "vendorReachable": False, "checks": checks, **result,
            "outcome": "passed" if all(checks.values()) else "failed"}


async def live() -> dict[str, Any]:
    env = clean_env()
    before = await usage(env)
    windows = before.get("windows", [])
    exhausted = any(window.get("limitReached") is True or isinstance(window.get("usedPercent"), (int, float))
                    and window["usedPercent"] >= 100 for window in windows)
    extra = object_value(before.get("extra"))
    ordinary = extra.get("ordinaryUsageAllowed")
    credits = object_value(extra.get("credits")).get("hasCredits") is True
    if (exhausted or ordinary is False) and ordinary is not True and not credits:
        return {"check": "live.errors-usage", "subscriptionId": SUBSCRIPTION, "inferenceRequests": 0,
                "usageBefore": shares(before), "outcome": "refused",
                "reason": "The vendor reports no available usage or credits; no prompt was sent."}
    result = await execute_run(env, total=60, idle=30)
    events = result["events"]
    final = events[-1] if events else {}
    code, output, error = await command(["subscriptions", "list"], env)
    records = json.loads(output)
    record: dict[str, Any] = next((item for item in records if item.get("id") == SUBSCRIPTION), {})
    cached = object_value(record.get("lastUsage"))
    after = await usage(env)
    answer = "".join(event.get("text", "") for event in events if event.get("type") == "text")
    observed = timestamp(cached.get("fetchedAt"))
    prior = timestamp(before.get("fetchedAt"))
    checks = {
        "completed": result["exitCode"] == 0 and final.get("type") == "finished" and final.get("outcome") == "completed",
        "tinyAnswer": answer.strip() == "OK",
        "noTools": not any(event.get("type") == "tool_started" for event in events),
        "usageReported": bool(object_value(final.get("usage"))),
        "runUsageStored": code == 0 and not error and cached.get("outcome") == "ok"
            and observed is not None and prior is not None and observed >= prior,
        "sparseExtrasPreserved": all(key in object_value(cached.get("extra")) for key in object_value(before.get("extra"))),
        "oneFinished": sum(event.get("type") == "finished" for event in events) == 1,
        "quietStderr": result["quietStderr"], "scratchRemoved": result["scratchRemoved"],
        "runRecordRemoved": result["runRecordRemoved"],
    }
    return {"check": "live.errors-usage", "subscriptionId": SUBSCRIPTION, "model": "gpt-5.6-luna", "effort": "low",
            "inferenceRequests": int(any(event.get("type") == "started" for event in events)),
            "usageBefore": shares(before), "runUsage": shares(cached), "usageAfter": shares(after),
            "usageChange": usage_change(before, after),
            "creditsBefore": object_value(before.get("extra")).get("credits"),
            "creditsAfter": object_value(after.get("extra")).get("credits"),
            "tokens": final.get("usage", {}), "checks": checks, **result,
            "outcome": "passed" if all(checks.values()) else "failed"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("probe", "live"))
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args()
    report = asyncio.run(probe() if arguments.mode == "probe" else live())
    report["at"] = datetime.now(UTC).isoformat()
    report["stateDirectory"] = str(STATE)
    Path(arguments.output).write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: value for key, value in report.items() if key != "events"}))
    return 0 if report["outcome"] == "passed" else 2 if report["outcome"] == "refused" else 1


if __name__ == "__main__":
    raise SystemExit(main())
