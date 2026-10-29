# Mid-tier source from scripts/check_tools.py; see MID_TIER.md.
# Shared helpers and refusal entry points remain at the original path.

# TEST-TIER-DISABLED-BEGIN scripts/check_tools.py
# """Explicit SYL-90 no-prompt and tiny live checks against the installed Codex.
#
# Never run this as part of the offline unit suite. Live mode uses only the named
# test Subscription, low effort, and one short request. Reports contain assertions
# and public tool events, never owner configuration or vendor account responses.
# """
#
# from __future__ import annotations
#
# import argparse
# import asyncio
# import json
# import os
# import shutil
# import sys
# import tempfile
# import time
# from datetime import UTC, datetime
# from pathlib import Path
# from typing import Any
#
# ROOT = Path(__file__).resolve().parent.parent
# sys.path.insert(0, str(ROOT / "src"))
#
# from arbol_codex_driver.app_server import AppServer  # noqa: E402
# from arbol_codex_driver.json_types import Json, object_value  # noqa: E402
# from arbol_codex_driver.owner_setup import diagnostic_values, owner_mcp_config  # noqa: E402
#
#
# def clean_env() -> dict[str, str]:
#     return {"HOME": str(Path.home()), "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
#             "LANG": "en_US.UTF-8", "TMPDIR": tempfile.gettempdir()}
#
#
# def snapshot() -> dict[str, tuple[int, int, int, int]]:
#     """Compare metadata only: never open owner's login or session files."""
#     result = {}
#     for tree in (Path.home() / ".codex", Path.home() / ".agents"):
#         for folder, directories, files in os.walk(tree, followlinks=False):
#             for name in [*directories, *files]:
#                 path = Path(folder) / name
#                 try:
#                     stat = path.lstat()
#                     result[str(path)] = (stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_mode)
#                 except FileNotFoundError:
#                     pass
#     return result
#
#
# async def probe() -> dict[str, Any]:
#     env = clean_env()
#     config = owner_mcp_config(env)
#     servers = object_value(config.get("mcp_servers"))
#     expected_servers = {name for name, value in servers.items() if object_value(value).get("enabled") is not False}
#     before = snapshot()
#     with tempfile.TemporaryDirectory(prefix="syl90-probe-") as name:
#         scratch = Path(name)
#         server = await AppServer.start(tool_path=shutil.which("codex", path=env["PATH"]) or "codex",
#                                        home=scratch / "home", cwd=scratch, env=env,
#                                        private_values=diagnostic_values(config))
#         try:
#             original = (scratch / "home/config.toml").read_bytes()
#             await server.request("thread/start", {"cwd": str(scratch), "ephemeral": True,
#                                                   "approvalPolicy": "never", "sandbox": "danger-full-access",
#                                                   **({"config": config} if config else {})})
#             skills = object_value(await server.request("skills/list", {"cwds": [str(scratch)], "forceReload": True}))
#             found: list[Json] = []
#             entries = skills.get("data", [])
#             assert isinstance(entries, list)
#             for entry in entries:
#                 if isinstance(entry, dict):
#                     rows = entry.get("skills", [])
#                     assert isinstance(rows, list)
#                     found.extend(rows)
#             owner_skills = [skill for skill in found if isinstance(skill, dict)
#                             and str(skill.get("path", "")).startswith(str(Path.home() / ".agents/skills"))]
#             # Thread-local MCP overrides are absent from the process-global
#             # mcpServerStatus/list result. Their startup notifications are the
#             # stable, observed discovery signal (the 6 October probe record).
#             discovered: set[str] = set()
#             statuses: dict[str, str] = {}
#             deadline = time.monotonic() + 15
#             while not expected_servers.issubset(discovered):
#                 remaining = deadline - time.monotonic()
#                 if remaining <= 0:
#                     break
#                 try:
#                     notice = await server.next_notification(timeout=remaining)
#                 except Exception:
#                     break
#                 if notice.method == "mcpServer/startupStatus/updated":
#                     params = object_value(notice.params)
#                     name_ = params.get("name")
#                     status_ = params.get("status")
#                     if isinstance(name_, str) and name_ in servers and isinstance(status_, str):
#                         discovered.add(name_)
#                         statuses[name_] = status_
#             checks = {"ownerSkillsDiscovered": bool(owner_skills),
#                       "ownerServersDiscovered": expected_servers.issubset(discovered),
#                       "privateConfigurationUnchanged": original == (scratch / "home/config.toml").read_bytes()}
#             version = server.tool_version
#         finally:
#             await server.end()
#     after = snapshot()
#     changed = set(before) ^ set(after)
#     changed.update(path for path in before.keys() & after.keys() if before[path] != after[path])
#     checks["ownerTreesUnchanged"] = not changed
#     setup_roots = [".codex/config.toml", ".codex/auth.json", ".codex/AGENTS.md", ".codex/skills",
#                    ".codex/hooks", ".codex/plugins", ".agents"]
#     changed_relative = sorted(str(Path(path).relative_to(Path.home())) for path in changed)
#     setup_changes = [path for path in changed_relative
#                      if any(path == prefix or path.startswith(prefix + "/") for prefix in setup_roots)]
#     checks["ownerSetupMetadataUnchanged"] = not setup_changes
#     return {"check": "probe.tools", "toolVersion": version, "inferenceRequests": 0,
#             "checks": checks, "ownerSkillCount": len(owner_skills), "ownerServerCount": len(servers),
#             "ownerEnabledServerCount": len(expected_servers),
#             "ownerDisabledServerCount": len(servers) - len(expected_servers),
#             "ownerServersAnnounced": len(discovered),
#             "ownerStartupStatusCounts": {status: list(statuses.values()).count(status) for status in set(statuses.values())},
#             "ownerMetadataChanges": len(changed),
#             "ownerChangedMetadataPaths": changed_relative,
#             "ownerSetupMetadataScope": setup_roots,
#             "ownerSetupMetadataChanges": setup_changes,
#             "outcome": "passed" if all(checks.values()) else "failed"}
#
#
# async def live(subscription: str, model: str) -> dict[str, Any]:
#     env = clean_env()
#     with tempfile.TemporaryDirectory(prefix="syl90-live-") as name:
#         scratch = Path(name)
#         work = scratch / "work"
#         work.mkdir()
#         outside = scratch / "outside.txt"
#         prompt = (
#             "Perform this short tools check. Do not inspect unrelated files or call MCP servers. "
#             f"Use a command to write SYL90_INSIDE to {work / 'inside.txt'} and SYL90_OUTSIDE to {outside}. "
#             "Fetch https://example.com with curl -fsS and print only the HTTP status. "
#             "Explicitly spawn exactly one sub-agent; its only task is a shell command 'sleep 1; echo SYL90_CHILD', "
#             "and its final answer must be exactly SYL90_CHILD. "
#             "Wait for that sub-agent. Then use exec_command to start 'sleep 8; echo SYL90_BACKGROUND' with "
#             "yield_time_ms 1; leave it running without polling. Immediately finish your own answer exactly SYL90_MAIN. "
#             "Keep the answer short."
#         )
#         request = scratch / "request.json"
#         request.write_text(json.dumps({"subscriptionId": subscription, "model": model, "effort": "low",
#                                        "tools": "all", "workingDirectory": str(work), "history": [],
#                                        "input": {"role": "user", "text": prompt}}))
#         state = Path.home() / "Library/Application Support/Arbol/drivers/arbol-codex-driver"
#         child = await asyncio.create_subprocess_exec(str(ROOT / "bin/arbol-codex-driver"), "run", "--state-dir",
#                                                      str(state), "--request", str(request), env=env, stdout=asyncio.subprocess.PIPE,
#                                                      stderr=asyncio.subprocess.PIPE)
#         assert child.stdout is not None and child.stderr is not None
#         events: list[dict[str, Any]] = []
#         timed: list[dict[str, Any]] = []
#         began = time.monotonic()
#         try:
#             async with asyncio.timeout(120):
#                 while line := await child.stdout.readline():
#                     event = json.loads(line)
#                     events.append(event)
#                     timed.append({"seconds": round(time.monotonic() - began, 3), "event": event})
#                 await child.wait()
#         except TimeoutError:
#             child.terminate()
#             await asyncio.wait_for(child.wait(), 20)
#             raise ValueError("The tiny tools check exceeded its explicit 120-second check bound.") from None
#         stderr = await child.stderr.read()
#         starts = {event["callId"]: event for event in events if event["type"] == "tool_started"}
#         finishes = {event["callId"]: event for event in events if event["type"] == "tool_finished"}
#         children = [event for event in events if event.get("parentCallId")]
#         answer = "".join(event.get("text", "") for event in events if event["type"] == "text" and not event.get("parentCallId"))
#         backgrounds = [event for event in starts.values() if event.get("name") == "shell"
#                        and "sleep 8" in str(event.get("input"))]
#         fetches = [event for event in starts.values() if event.get("name") == "shell"
#                    and "curl" in str(event.get("input"))]
#         checks = {
#             "completed": child.returncode == 0 and bool(events) and events[-1].get("outcome") == "completed",
#             "writesInsideAndOutside": (work / "inside.txt").read_text().strip() == "SYL90_INSIDE"
#                 and outside.read_text().strip() == "SYL90_OUTSIDE" if (work / "inside.txt").exists() and outside.exists() else False,
#             "networkFetchSucceeded": any(finishes.get(event["callId"], {}).get("ok") for event in fetches),
#             "childEventsAttributed": bool(children) and all(event["parentCallId"] in starts for event in children),
#             "childTextExcluded": any(event["type"] == "text" and "SYL90_CHILD" in event.get("text", "")
#                                       for event in children) and "SYL90_CHILD" not in answer,
#             "backgroundResultReported": any("SYL90_BACKGROUND" in str(finishes.get(event["callId"], {}).get("result"))
#                                               and finishes.get(event["callId"], {}).get("ok") for event in backgrounds),
#             "backgroundResultAfterAnswer": any(next((i for i, event in enumerate(events) if event.get("callId") == start["callId"]
#                                                       and event["type"] == "tool_finished"), -1)
#                                                 > max((i for i, event in enumerate(events) if event["type"] == "text"
#                                                        and not event.get("parentCallId")), default=-1) for start in backgrounds),
#             "noQuestions": not any(event["type"].startswith("ask_") for event in events),
#             "callsClosedOnce": all(sum(event.get("callId") == call_id and event["type"] == "tool_finished"
#                                         for event in events) == 1 for call_id in starts),
#             "orderedEvents": [event.get("seq") for event in events] == list(range(1, len(events) + 1)),
#             "quietStderr": not stderr,
#         }
#         return {"check": "live.tools", "subscriptionId": subscription, "model": model, "effort": "low",
#                 "inferenceRequests": int(any(event["type"] == "started" for event in events)),
#                 "stateDirectory": str(state), "seconds": round(time.monotonic() - began, 3), "checks": checks,
#                 "events": timed, "outcome": "passed" if all(checks.values()) else "failed"}
#
#
# def main() -> int:
#     parser = argparse.ArgumentParser(description=__doc__)
#     parser.add_argument("mode", choices=("probe", "live"))
#     parser.add_argument("--subscription", default="test-chatgpt", choices=("test-chatgpt",))
#     parser.add_argument("--model", default="gpt-5.6-luna")
#     parser.add_argument("--output", required=True)
#     arguments = parser.parse_args()
#     report = asyncio.run(probe() if arguments.mode == "probe" else live(arguments.subscription, arguments.model))
#     report["at"] = datetime.now(UTC).isoformat()
#     Path(arguments.output).write_text(json.dumps(report, indent=2) + "\n")
#     print(json.dumps({key: value for key, value in report.items() if key != "events"}))
#     return 0 if report["outcome"] == "passed" else 1
#
#
# if __name__ == "__main__":
#     raise SystemExit(main())
# TEST-TIER-DISABLED-END scripts/check_tools.py


raise RuntimeError("Mid-tier checks require an explicitly requested testing task; see MID_TIER.md.")
