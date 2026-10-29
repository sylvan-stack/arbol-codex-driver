# Mid-tier source from src/arbol_codex_driver/dev.py; see MID_TIER.md.
# Shared helpers and refusal entry points remain at the original path.

# TEST-TIER-DISABLED-BEGIN src/arbol_codex_driver/dev.py::probe
# async def probe(
#     subscriptions: Subscriptions, inherited: dict[str, str], cancellation: Cancellation
# ) -> tuple[int, Object]:
#     checks: list[Json] = []
#     report: Object = {
#         "check": "dev.probe",
#         "at": now(),
#         "inferenceRequests": 0,
#         "provenance": provenance(),
#         "checks": checks,
#     }
#     temporary = subscriptions.state.directory / "tmp"
#     private_directory(temporary)
#     directory = Path(tempfile.mkdtemp(prefix="probe-", dir=temporary))
#     server: AppServer | None = None
#     status = 0
#     try:
#         tool = await inspect_tool(
#             subscriptions.state, string(subscriptions.settings.get("toolPath")), inherited, cancellation
#         )
#         program = require_tool(tool)
#         report["toolVersion"] = tool["version"]
#         owner = directory / "owner"
#         private_directory(owner)
#         private_directory(directory / "schema-home")
#         env = clean_environment(inherited, str(owner), str(directory / "schema-home"))
#         env["TMPDIR"] = str(directory)
#         schema_directory = directory / "schema"
#         code, _ = await command(
#             program,
#             ["app-server", "generate-json-schema", "--out", str(schema_directory)],
#             env,
#             directory,
#             cancellation,
#         )
#         verify(code == 0, "codex did not generate its stable protocol schema.")
#         schemas: Object = {}
#         for name, fields in SCHEMA_FIELDS.items():
#             schema = object_value(read_schema(schema_directory, name))
#             properties = object_value(schema.get("properties"))
#             verify(fields.issubset(properties), f"codex changed the stable {name} fields.")
#             schemas[name] = {"fields": cast(list[Json], sorted(properties)), "required": schema.get("required", [])}
#         login_schema = read_schema(schema_directory, "LoginAccountParams")
#         verify(
#             {"chatgpt", "chatgptDeviceCode"}.issubset(schema_enums(login_schema)),
#             "codex changed its stable ChatGPT login types.",
#         )
#         schemas["LoginAccountParams"] = {"loginTypes": ["chatgpt", "chatgptDeviceCode"]}
#         error_schema = object_value(
#             object_value(read_schema(schema_directory, "ErrorNotification")).get("definitions")
#         ).get("CodexErrorInfo")
#         verify(isinstance(error_schema, dict), "codex did not include its stable CodexErrorInfo definition.")
#         error_enums = schema_enums(error_schema)
#         verify(
#             {"contextWindowExceeded", "usageLimitExceeded", "other"}.issubset(error_enums),
#             "codex changed its stable error classes.",
#         )
#         schemas["CodexErrorInfo"] = {"classes": cast(list[Json], sorted(error_enums))}
#         checks.append(
#             {
#                 "check": "probe.stable-schema",
#                 "outcome": "passed",
#                 "experimentalSchemaIncluded": False,
#                 "requests": schemas,
#             }
#         )
#         config_home = directory / "home"
#         server = await AppServer.start(
#             tool_path=program, home=config_home, cwd=directory, env=env, cancellation=cancellation
#         )
#         verify(server.tool_version == tool["version"], "codex changed its handshake version.")
#         original = (config_home / "config.toml").read_bytes()
#         checks.append(
#             {
#                 "check": "probe.base-info",
#                 "outcome": "passed",
#                 "configuration": probe_shape(server.effective_config),
#                 "handshakeVersion": server.tool_version,
#                 "privateHome": True,
#             }
#         )
#         account = object_value(await server.request("account/read", {}, cancellation=cancellation))
#         verify(account.get("account") is None, "A disposable Codex home unexpectedly has an account.")
#         models = await server.request("model/list", {}, cancellation=cancellation)
#         checks.append(
#             {
#                 "check": "probe.subscriptions",
#                 "outcome": "passed",
#                 "account": probe_shape(account),
#                 "models": probe_shape(models),
#             }
#         )
#         skill = owner / ".agents/skills/arbol-probe/SKILL.md"
#         private_directory(skill.parent)
#         skill.write_text(
#             "---\nname: arbol-probe\ndescription: Synthetic discovery probe\n---\nNo inference is requested.\n"
#         )
#         tools = await server.request(
#             "thread/start",
#             {
#                 "cwd": str(directory),
#                 "approvalPolicy": "never",
#                 "sandbox": "danger-full-access",
#                 "ephemeral": True,
#                 "config": {"mcp_servers": {"arbol-probe": {"command": sys.executable, "args": ["-I", "-c", "pass"]}}},
#             },
#             cancellation=cancellation,
#         )
#         skills = object_value(
#             await server.request(
#                 "skills/list", {"cwds": [str(directory)], "forceReload": True}, cancellation=cancellation
#             )
#         )
#         data = skills.get("data", [])
#         found: list[Object] = []
#         if isinstance(data, list):
#             for entry in data:
#                 entries = object_value(entry).get("skills", [])
#                 if isinstance(entries, list):
#                     found.extend(object_value(value) for value in entries)
#         verify(
#             any(value.get("name") == "arbol-probe" for value in found),
#             "codex did not discover the disposable probe skill.",
#         )
#         checks.append(
#             {
#                 "check": "probe.tools",
#                 "outcome": "passed",
#                 "thread": probe_shape(tools),
#                 "skills": probe_shape(skills),
#                 "ownerSetup": "synthetic disposable HOME only",
#             }
#         )
#         login = object_value(
#             await server.request("account/login/start", {"type": "chatgptDeviceCode"}, cancellation=cancellation)
#         )
#         login_id = string(login.get("loginId"))
#         verify(
#             login_id is not None
#             and isinstance(login.get("verificationUrl"), str)
#             and isinstance(login.get("userCode"), str),
#             "codex changed its device-code login response.",
#         )
#         cancelled = await server.request("account/login/cancel", {"loginId": login_id}, cancellation=cancellation)
#         logout = await server.request("account/logout", {}, cancellation=cancellation)
#         checks.append(
#             {
#                 "check": "probe.device-login",
#                 "outcome": "passed",
#                 "login": probe_shape(login),
#                 "cancel": probe_shape(cancelled),
#                 "logout": probe_shape(logout),
#                 "localLogin": "schema only; a shared browser callback can replace a pending owner login",
#             }
#         )
#         started = object_value(
#             await server.request(
#                 "thread/start",
#                 {"cwd": str(directory), "approvalPolicy": "never", "sandbox": "read-only", "ephemeral": False},
#                 cancellation=cancellation,
#             )
#         )
#         thread = string(object_value(started.get("thread")).get("id"))
#         verify(thread is not None, "codex did not return a saved probe thread.")
#         history: list[Object] = [
#             {"type": "message", "role": "user", "text": "Synthetic history; never sent for inference."},
#             {
#                 "type": "tool_call",
#                 "name": "shell",
#                 "input": {"command": "printf fixture"},
#                 "ok": False,
#                 "result": {"output": "fixture", "exitCode": 1},
#             },
#         ]
#         injected = await server.request(
#             "thread/inject_items", {"threadId": thread, "items": history_items(history)}, cancellation=cancellation
#         )
#         read = await server.request(
#             "thread/read", {"threadId": thread, "includeTurns": True}, cancellation=cancellation
#         )
#         checks.append(
#             {
#                 "check": "probe.continuity",
#                 "outcome": "passed",
#                 "start": probe_shape(started),
#                 "injected": probe_shape(injected),
#                 "read": probe_shape(read),
#             }
#         )
#         # No turn has started: this checks refusal shape without a model request.
#         try:
#             await server.request(
#                 "turn/interrupt",
#                 {"threadId": str(uuid.uuid4()), "turnId": str(uuid.uuid4())},
#                 cancellation=cancellation,
#             )
#         except Failure as failure:
#             if "vendorCode" not in object_value(failure.result.get("detail")):
#                 raise
#             checks.append({"check": "probe.stopping", "outcome": "passed", "refusal": probe_shape(failure.result)})
#         else:
#             checks.append({"check": "probe.stopping", "outcome": "passed", "response": "empty success"})
#         verify((config_home / "config.toml").read_bytes() == original, "codex changed the probe configuration.")
#         await server.end()
#         server = await AppServer.start(
#             tool_path=program, home=config_home, cwd=directory, env=env, cancellation=cancellation
#         )
#         resumed = await server.request("thread/resume", {"threadId": thread}, cancellation=cancellation)
#         checks.append({"check": "probe.resume", "outcome": "passed", "response": probe_shape(resumed)})
#         await server.end()
#         server = None
#         # An existing designated test home may be queried, never copied. No
#         # thread, login or prompt is started in it, and no account values saved.
#         if SUBSCRIPTION in subscriptions.ids() and (await subscriptions.get(SUBSCRIPTION))["state"] == "signed_in":
#             verify(
#                 subscriptions.file(SUBSCRIPTION, "home").is_dir(),
#                 "The signed-in test Subscription home is missing; the probe will not recreate it.",
#             )
#             server = await subscriptions.start(SUBSCRIPTION)
#             signed_account = await server.request("account/read", {}, cancellation=cancellation)
#             usage = await server.request("account/rateLimits/read", {}, cancellation=cancellation)
#             checks.append(
#                 {
#                     "check": "probe.signed-subscription",
#                     "outcome": "passed",
#                     "subscriptionId": SUBSCRIPTION,
#                     "account": probe_shape(signed_account),
#                     "usage": probe_shape(usage),
#                 }
#             )
#     except Exception as failure:
#         status = 2 if cancellation.aborted else 1
#         public = safe_failure(failure)
#         report["failureShape"] = probe_shape(public)
#         error: Object = {
#             "code": public["code"],
#             "retryable": public["retryable"],
#             "message": public["message"]
#             if public["code"] in ("tool_unsupported", "tool_missing")
#             else "The Codex probe failed; inspect the failing check and response shapes in its record.",
#         }
#         if public["code"] in ("tool_unsupported", "tool_missing"):
#             # Version refusals are public, bounded facts from inspect_tool and
#             # require_tool. Preserve their contract fields while leaving all
#             # arbitrary vendor diagnostics only in failureShape.
#             version_detail: Object = {
#                 key: value
#                 for key, value in object_value(public.get("detail")).items()
#                 if key == "basis"
#                 and value == "fields"
#                 or key in ("neededVersion", "toolVersion")
#                 and isinstance(value, str)
#                 and (value == "unknown" or re.fullmatch(r"\d+\.\d+\.\d+", value))
#             }
#             if version_detail:
#                 error["detail"] = version_detail
#             if public.get("remedy") in ("Install codex.", "Update codex."):
#                 error["remedy"] = public["remedy"]
#         report["error"] = error
#         checks.append({"check": "probe.failure", "outcome": "failed"})
#     finally:
#         try:
#             if server is not None:
#                 await server.end()
#         except Exception as failure:
#             status = 2 if cancellation.aborted else 1
#             report["failureShape"] = probe_shape(safe_failure(failure))
#             report["error"] = {
#                 "code": "tool_failed",
#                 "retryable": False,
#                 "message": "The Codex probe could not finish its process cleanup.",
#             }
#             checks.append({"check": "probe.cleanup", "outcome": "failed"})
#         finally:
#             shutil.rmtree(directory, ignore_errors=True)
#     report["outcome"] = "passed" if status == 0 else "cancelled" if status == 2 else "failed"
#     return status, save_report(subscriptions.state, report)
# TEST-TIER-DISABLED-END src/arbol_codex_driver/dev.py::probe

# TEST-TIER-DISABLED-BEGIN src/arbol_codex_driver/dev.py::live_check
# async def live_check(
#     build_only: bool, subscriptions: Subscriptions, inherited: dict[str, str], cancellation: Cancellation
# ) -> tuple[int, Object]:
#     checks: list[Json] = []
#     report: Object = {
#         "check": "dev.build-check" if build_only else "dev.live-check",
#         "at": now(),
#         "subscriptionId": SUBSCRIPTION,
#         "turnsAttempted": 0,
#         "inferenceRequests": 0,
#         "inferenceCountBasis": "observed Driver started events; vendor requests and child turns can exceed this count",
#         "spendMayBeIncomplete": False,
#         "tokenUsage": {},
#         "tokenUsageBasis": "main Driver turns; child token usage is reported separately when available",
#         "childTokenUsage": {},
#         "checks": checks,
#         "provenance": provenance(),
#     }
#     before: Object = {}
#     directory: Path | None = None
#     status = 0
#     try:
#         before = await check_account(subscriptions)
#         report["usageBefore"] = before
#         tool = await inspect_tool(
#             subscriptions.state, string(subscriptions.settings.get("toolPath")), inherited, cancellation
#         )
#         require_tool(tool)
#         report["toolVersion"] = tool["version"]
#         model, effort = select_model(await subscriptions.models(SUBSCRIPTION))
#         report.update(model=model, **({"effort": effort} if effort else {}))
#         temporary = subscriptions.state.directory / "tmp"
#         private_directory(temporary)
#         directory = Path(tempfile.mkdtemp(prefix="build-check-" if build_only else "live-check-", dir=temporary))
#
#         async def message(
#             name: str,
#             prompt: str,
#             *,
#             tools: bool = False,
#             stop: bool = False,
#             chat: str | None = None,
#             history: list[Json] | None = None,
#         ) -> tuple[list[Object], str]:
#             assert directory is not None
#             await check_account(subscriptions)
#             cancellation.check()
#             request: Object = {
#                 "subscriptionId": SUBSCRIPTION,
#                 "model": model,
#                 "tools": "all" if tools else "none",
#                 "history": history or [],
#                 "input": {"role": "user", "text": prompt},
#                 "limits": {"totalSeconds": 60, "idleSeconds": 30},
#                 **({"effort": effort} if effort else {}),
#                 **({"workingDirectory": str(directory)} if tools or chat else {}),
#                 **({"chatSessionId": chat} if chat else {}),
#             }
#             report["turnsAttempted"] = cast(int, report["turnsAttempted"]) + 1
#             events: list[Object] = []
#             exit_code: int | None = None
#             try:
#                 exit_code, events = await execute_run(subscriptions, inherited, directory, request, cancellation, stop)
#             except Failure as failure:
#                 partial = failure.result.pop("devEvents", [])
#                 events = [object_value(item) for item in partial] if isinstance(partial, list) else []
#                 raise
#             finally:
#                 started = any(event.get("type") == "started" for event in events)
#                 report["inferenceRequests"] = cast(int, report["inferenceRequests"]) + int(started)
#                 final = events[-1] if events else {}
#                 if not started or final.get("type") != "finished":
#                     report["spendMayBeIncomplete"] = True
#                 usage = object_value(
#                     final.get(
#                         "usage",
#                         next(
#                             (
#                                 event.get("usage")
#                                 for event in reversed(events)
#                                 if event.get("type") == "usage" and not event.get("parentCallId")
#                             ),
#                             {},
#                         ),
#                     )
#                 )
#                 aggregate = object_value(report["tokenUsage"])
#                 for key, value in usage.items():
#                     if number(value):
#                         aggregate[key] = cast(float, aggregate.get(key, 0)) + cast(float, value)
#                     elif key == "model":
#                         aggregate[key] = value
#                 report["tokenUsage"] = aggregate
#                 child_usage: Object = {}
#                 for event in events:
#                     parent = string(event.get("parentCallId"))
#                     if event.get("type") == "usage" and parent is not None:
#                         child_usage[parent] = event.get("usage")
#                 child_aggregate = object_value(report["childTokenUsage"])
#                 if any(event.get("parentCallId") for event in events) and not child_usage:
#                     report["spendMayBeIncomplete"] = True
#                 for value in child_usage.values():
#                     for key, amount in object_value(value).items():
#                         if number(amount):
#                             child_aggregate[key] = cast(float, child_aggregate.get(key, 0)) + cast(float, amount)
#                 report["childTokenUsage"] = child_aggregate
#                 checks.append(
#                     {
#                         "check": name,
#                         "outcome": final.get("outcome", "failed"),
#                         "exit": exit_code,
#                         "inferenceRequests": int(started),
#                         "tokenUsage": usage,
#                         "childTokenUsage": list(child_usage.values()),
#                         "childTokenUsageReported": bool(child_usage),
#                         "eventTypes": [event.get("type") for event in events],
#                         "continuity": events[0].get("continuity") if events else None,
#                         **({"error": final["error"]} if "error" in final else {}),
#                     }
#                 )
#             verify(
#                 sum(event.get("type") == "finished" for event in events) == 1
#                 and events[-1].get("outcome") == ("cancelled" if stop else "completed")
#                 and exit_code == (2 if stop else 0),
#                 f"The {name} run did not finish as expected.",
#             )
#             verify(
#                 [event.get("seq") for event in events] == list(range(1, len(events) + 1)),
#                 f"The {name} run did not preserve event order.",
#             )
#             answer = "".join(
#                 str(event.get("text", ""))
#                 for event in events
#                 if event.get("type") == "text" and not event.get("parentCallId")
#             )
#             return events, answer
#
#         events, answer = await message("live.ready-usage", READY)
#         verify(re.search(r"\bready\b", answer, re.I), "The ready check did not produce the expected answer.")
#         if not build_only:
#             events, answer = await message(
#                 "live.tools-background",
#                 "Run printf ready. Explicitly start exactly one sub-agent; "
#                 "its only task is to run printf ARBOL_CHILD and answer ARBOL_CHILD. Wait for it. "
#                 "Then start 'sleep 2; printf ARBOL_BACKGROUND' with yield_time_ms 1 and leave it running. "
#                 "Finish your answer with ready. Do not inspect other files or call MCP servers.",
#                 tools=True,
#             )
#             starts = {str(event.get("callId")): event for event in events if event.get("type") == "tool_started"}
#             background = {
#                 call
#                 for call, event in starts.items()
#                 if event.get("name") == "shell" and "sleep 2" in str(event.get("input"))
#             }
#             answer_at = max(
#                 (
#                     index
#                     for index, event in enumerate(events)
#                     if event.get("type") == "text" and not event.get("parentCallId")
#                 ),
#                 default=-1,
#             )
#             verify(
#                 any(
#                     event.get("type") == "text"
#                     and event.get("parentCallId") in starts
#                     and "ARBOL_CHILD" in str(event.get("text"))
#                     for event in events
#                 )
#                 and "ARBOL_CHILD" not in answer
#                 and re.search(r"\bready\b", answer, re.I)
#                 and any(
#                     index > answer_at
#                     and event.get("type") == "tool_finished"
#                     and str(event.get("callId")) in background
#                     and event.get("ok") is True
#                     and "ARBOL_BACKGROUND" in str(event.get("result"))
#                     for index, event in enumerate(events)
#                 ),
#                 "The tools, child attribution or late background result check did not produce the expected behavior.",
#             )
#             chat = str(uuid.uuid4())
#             prompt = "Remember the word willow. Answer only ready."
#             _, first = await message("live.continuity-fresh", prompt, chat=chat)
#             history: list[Json] = [
#                 {"type": "message", "role": "user", "text": prompt},
#                 {"type": "message", "role": "assistant", "text": first},
#             ]
#             events, answer = await message(
#                 "live.continuity-resumed",
#                 "What word did I give you? Answer only that word.",
#                 chat=chat,
#                 history=history,
#             )
#             verify(
#                 events[0].get("continuity") == "resumed" and re.search(r"\bwillow\b", answer, re.I),
#                 "The continuity check did not resume and recall the expected word.",
#             )
#             await message("live.stopping", "Run sleep 8 then printf ready.", tools=True, stop=True)
#     except Exception as failure:
#         status = 2 if cancellation.aborted else 1
#         report["error"] = safe_failure(failure)
#     finally:
#         if directory is not None:
#             shutil.rmtree(directory, ignore_errors=True)
#         # Refresh after failures too: failed attempts can consume quota. Keep an
#         # unavailable outcome instead of silently claiming the old usage value.
#         if before:
#             try:
#                 after = await subscriptions.usage(SUBSCRIPTION)
#             except Exception as failure:
#                 after = {"outcome": "unavailable", "fetchedAt": now(), "windows": [], "error": safe_failure(failure)}
#             report.update(usageAfter=after, usageChange=usage_change(before, after))
#     report["outcome"] = "passed" if status == 0 else "cancelled" if status == 2 else "failed"
#     return status, save_report(subscriptions.state, report)
# TEST-TIER-DISABLED-END src/arbol_codex_driver/dev.py::live_check

# TEST-TIER-IMPORTS-BEGIN src/arbol_codex_driver/dev.py:4
# import re
# TEST-TIER-IMPORTS-END src/arbol_codex_driver/dev.py:4

# TEST-TIER-IMPORTS-BEGIN src/arbol_codex_driver/dev.py:5
# import shutil
# TEST-TIER-IMPORTS-END src/arbol_codex_driver/dev.py:5

# TEST-TIER-IMPORTS-BEGIN src/arbol_codex_driver/dev.py:6
# import sys
# TEST-TIER-IMPORTS-END src/arbol_codex_driver/dev.py:6

# TEST-TIER-IMPORTS-BEGIN src/arbol_codex_driver/dev.py:7
# import tempfile
# TEST-TIER-IMPORTS-END src/arbol_codex_driver/dev.py:7

# TEST-TIER-IMPORTS-BEGIN src/arbol_codex_driver/dev.py:12
# from .app_server import AppServer
# TEST-TIER-IMPORTS-END src/arbol_codex_driver/dev.py:12

# TEST-TIER-IMPORTS-BEGIN src/arbol_codex_driver/dev.py:14
# from .dev_support import (
#     READY,
#     SUBSCRIPTION,
#     command,
#     driver_environment,
#     probe_shape,
#     provenance,
#     refuse_exhausted,
#     save_report,
#     schema_enums,
#     stop_child,
#     usage_change,
#     verify,
# )
# TEST-TIER-IMPORTS-END src/arbol_codex_driver/dev.py:14

# TEST-TIER-IMPORTS-BEGIN src/arbol_codex_driver/dev.py:28
# from .environment import clean_environment
# TEST-TIER-IMPORTS-END src/arbol_codex_driver/dev.py:28

# TEST-TIER-IMPORTS-BEGIN src/arbol_codex_driver/dev.py:29
# from .errors import Failure, safe_failure
# TEST-TIER-IMPORTS-END src/arbol_codex_driver/dev.py:29

# TEST-TIER-IMPORTS-BEGIN src/arbol_codex_driver/dev.py:30
# from .history import history_items
# TEST-TIER-IMPORTS-END src/arbol_codex_driver/dev.py:30

# TEST-TIER-IMPORTS-BEGIN src/arbol_codex_driver/dev.py:31
# from .json_types import Json, Object, loads, now, number, object_value, string
# TEST-TIER-IMPORTS-END src/arbol_codex_driver/dev.py:31

# TEST-TIER-IMPORTS-BEGIN src/arbol_codex_driver/dev.py:33
# from .state import private_directory, write_json
# TEST-TIER-IMPORTS-END src/arbol_codex_driver/dev.py:33

# TEST-TIER-IMPORTS-BEGIN src/arbol_codex_driver/dev.py:35
# from .tool import inspect_tool, require_tool
# TEST-TIER-IMPORTS-END src/arbol_codex_driver/dev.py:35

raise RuntimeError("Mid-tier checks require an explicitly requested testing task; see MID_TIER.md.")
