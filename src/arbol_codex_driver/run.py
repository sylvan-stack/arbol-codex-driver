import asyncio
import os
import re
import shutil
import time
from pathlib import Path

from .app_server import AppServer
from .arguments import Command
from .cancellation import Cancellation, interruptible
from .catalog import normalize_account, read_model_catalog
from .continuity import Chats, MessageDigest
from .errors import Failure
from .event_stream import EventStream
from .history import history_items, labelled_history_input, prepare_turn_input
from .input_stream import Input
from .json_types import Json, Object, loads, object_value, string
from .run_events import RunEvents
from .run_request import RunRequest, read_run_request
from .runs import Runs
from .state import Owner, fixed_wait, owner_json, private_directory, read_json, write_json
from .subscriptions import Subscriptions
from .tool import inspect_tool, require_tool


async def interrupt_turns(server: AppServer, mapper: RunEvents, deadline: float) -> None:
    sent: set[str] = set()
    pending: list[asyncio.Task[Json]] = []
    try:
        for notice in server.take_notifications():
            mapper.consume(notice.method, notice.params)
        while time.monotonic() < deadline:
            for turn in mapper.active_turns:
                key = str(turn["threadId"]) + ":" + str(turn["turnId"])
                if key not in sent:
                    sent.add(key)
                    pending.append(
                        asyncio.create_task(
                            server.request("turn/interrupt", turn, timeout=max(0.001, deadline - time.monotonic()))
                        )
                    )
            if not mapper.active_turns and not mapper.has_active_agents:
                break
            try:
                notification = await server.next_notification(timeout=max(0.001, deadline - time.monotonic()))
            except Failure:
                break
            mapper.consume(notification.method, notification.params)
    finally:
        for task in pending:
            if not task.done():
                task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)


async def run(
    command: Command,
    subscriptions: Subscriptions,
    events: EventStream,
    env: dict[str, str],
    build: str,
    cancellation: Cancellation,
) -> int:
    input_: Input | None = None
    server: AppServer | None = None
    mapper: RunEvents | None = None
    error: BaseException | None = None
    temporary: Path | None = None
    reserved_id: str | None = None
    control_task: asyncio.Task[None] | None = None
    settled = False
    started = False
    request: RunRequest | None = None
    plan: Object | None = None
    conversation: str | None = None
    current_model: str | None = None
    fingerprint = MessageDigest()
    chats = Chats(subscriptions.state)
    pending_notices: list[Object] = []
    events.output.on_error = cancellation.abort
    runs = Runs(subscriptions.state, env)
    end_stop: asyncio.Task[None] | None = None
    try:
        if command.options.get("request") == "-" or command.options.get("control"):
            input_ = Input()
            await input_.open()

        async def first_line() -> str:
            cancellation.check()
            assert input_ is not None
            line = await interruptible(input_.line(), cancellation)
            if line is None:
                if command.options.get("control"):
                    cancellation.abort()
                raise Failure("invalid_input", "The request line is missing.")
            return line

        request = await read_run_request(
            command.options,
            settings=subscriptions.settings,
            message=command.positionals[0] if command.positionals else None,
            first_line=first_line,
            identity=events.identity,
        )
        events.text_only = request.output == "text"
        await runs.list()
        for item in request.history:
            fingerprint.add(item)
        fingerprint.add({**request.input, "type": "message"})
        if not request.control and input_ is not None:
            input_.close()
        subscription = await subscriptions.require_signed_in(request.subscription_id)
        parsed = request

        async def reserve() -> Object:
            nonlocal reserved_id, plan
            current = subscriptions.record(str(subscription["id"]))
            if current["state"] != "signed_in":
                raise Failure("not_signed_in", "Sign in to this Subscription first.")
            if read_json(subscriptions.file(parsed.subscription_id, "sign-in.json")) is not None:
                raise Failure("in_use", "An account operation is still in progress.")
            record = await runs.reserve(parsed.run_id, parsed.subscription_id, parsed.labels, parsed.chat_session_id)
            reserved_id = parsed.run_id
            plan = await chats.select(parsed, subscriptions.file(parsed.subscription_id, "home"))
            for key in ("conversation", "continuedConversation"):
                if key in plan:
                    record[key] = plan[key]
            runs.save(record)
            return record

        record = await subscriptions.state.with_subscription_lock(request.subscription_id, reserve, env)
        temporary = subscriptions.state.directory / "tmp" / request.run_id
        private_directory(temporary)
        work = Path(request.working_directory) if request.working_directory is not None else temporary / "work"
        if request.working_directory is None:
            private_directory(work)
        cwd = work.resolve(strict=True)
        child_env = env.copy()
        if request.search_path:
            child_env["PATH"] = child_env.get("PATH", "") + os.pathsep + os.pathsep.join(request.search_path)
        if request.control:

            async def control() -> None:
                assert input_ is not None
                try:
                    while (line := await input_.line()) is not None:
                        try:
                            value = loads(line)
                        except ValueError:
                            value = None
                        if isinstance(value, dict) and value.get("type") == "stop" and len(value) == 1:
                            cancellation.abort()
                            return
                        answer = isinstance(value, dict) and value.get("type") == "answer"
                        events.emit(
                            "control_refused",
                            {
                                "error": Failure(
                                    "not_found" if answer else "invalid_input",
                                    "That question is not open." if answer else "This control line is not accepted.",
                                ).result,
                                **(
                                    {"askId": value["askId"]}
                                    if isinstance(value, dict) and isinstance(value.get("askId"), str)
                                    else {}
                                ),
                            },
                        )
                except (OSError, ValueError):
                    pass
                finally:
                    if not settled:
                        cancellation.abort()

            control_task = asyncio.create_task(control())
        tool = await inspect_tool(
            subscriptions.state, string(subscriptions.settings.get("toolPath")), env, cancellation
        )

        async def spawned(owner: Owner) -> None:
            record["tool"] = owner_json(owner)
            runs.save(record)

        def server_request(method: str, params: Json) -> Json:
            notice: Object = {
                "code": "unexpected_request",
                "message": f"codex sent {method}; there is nobody to answer a question in this run.",
            }
            if started:
                events.emit("notice", notice)
            else:
                pending_notices.append(notice)
            return (
                {"decision": "accept"}
                if method in ("item/commandExecution/requestApproval", "item/fileChange/requestApproval")
                else None
            )

        server = await AppServer.start(
            tool_path=require_tool(tool),
            home=subscriptions.file(request.subscription_id, "home"),
            cwd=cwd,
            env=child_env,
            cancellation=cancellation,
            request_timeout=fixed_wait(30000, env),
            launch_identity_path=temporary / "tool-owner.txt",
            on_spawn=spawned,
            on_server_request=server_request,
        )
        account = normalize_account(await server.request("account/read", {}, cancellation=cancellation))
        if account is None:
            await subscriptions.run_report(
                subscription,
                Failure(
                    "credential_rejected", "The Codex home has no ChatGPT account.", {"remedy": "Sign in again."}
                ).result,
            )
            raise Failure("not_signed_in", "The Codex home has no ChatGPT account.", {"remedy": "Sign in again."})

        async def rpc(method: str, params: Json) -> Json:
            assert server is not None
            return await server.request(method, params, cancellation=cancellation)

        catalog = await read_model_catalog(rpc, fallback=False)
        models = catalog["models"]
        assert isinstance(models, list)
        configured_model = string(server.effective_config.get("model"))
        wanted = request.model or configured_model
        model = next(
            (
                item
                for item in models
                if isinstance(item, dict) and (item["id"] == wanted if wanted is not None else item.get("isDefault"))
            ),
            None,
        )
        if not isinstance(model, dict):
            raise Failure(
                "invalid_input" if request.model else "tool_failed",
                "The requested model is not in the tool catalog."
                if request.model
                else "Codex did not identify its default model in the catalog.",
            )
        configured_effort = string(server.effective_config.get("model_reasoning_effort"))
        effort = request.effort or configured_effort or string(model.get("defaultEffort"))
        efforts = model.get("efforts", [])
        tiers = model.get("serviceTiers", [])
        assert isinstance(efforts, list) and isinstance(tiers, list)
        if request.effort_from_settings and request.effort and request.effort not in efforts:
            pending_notices.append(
                {
                    "code": "ignored_default_effort",
                    "message": "The Subscription default effort is not supported by this model; the tool default is used.",
                }
            )
            effort = configured_effort or string(model.get("defaultEffort"))
        if effort and effort not in efforts:
            raise Failure("invalid_input", "The requested effort is not supported by the model.")
        if request.service_tier and request.service_tier not in tiers:
            raise Failure("invalid_input", "The requested service tier is not supported by the model.")
        assert plan is not None
        thread: Json = None
        if plan["continuity"] == "resumed":
            try:
                thread = await rpc("thread/resume", {"threadId": plan["conversation"], "model": model["id"]})
            except Failure as failure:
                if "vendorCode" not in object_value(failure.result.get("detail")) or cancellation.aborted:
                    raise
                plan.update(
                    continuity="rebuilt",
                    rebuildReason="conversation_gone"
                    if re.search(r"no rollout found|thread not found|unknown thread|does not exist", str(failure), re.I)
                    else "resume_refused",
                )
        if plan["continuity"] != "resumed":
            thread = await rpc(
                "thread/start",
                {
                    "cwd": str(cwd),
                    "model": model["id"],
                    "approvalPolicy": "never",
                    "sandbox": "read-only" if request.tools == "none" else "danger-full-access",
                    **({"serviceTier": request.service_tier} if request.service_tier is not None else {}),
                    **({"developerInstructions": request.system_prompt} if request.system_prompt is not None else {}),
                    **({"ephemeral": True} if request.tools == "none" and request.working_directory is None else {}),
                },
            )
        thread_record = object_value(thread)
        native_thread = object_value(thread_record.get("thread"))
        if not isinstance(native_thread.get("id"), str) or not isinstance(thread_record.get("model"), str):
            raise Failure("tool_failed", "Codex returned a malformed thread.")
        restored = native_thread.get("turns", [])
        restored_turns = (
            {str(turn["id"]) for turn in restored if isinstance(turn, dict) and isinstance(turn.get("id"), str)}
            if isinstance(restored, list)
            else set()
        )
        conversation, current_model = str(native_thread["id"]), str(thread_record["model"])
        record["conversation"] = conversation
        runs.save(record)
        turn_input = request.input
        if plan["continuity"] == "rebuilt" and request.history:
            try:
                await rpc("thread/inject_items", {"threadId": conversation, "items": history_items(request.history)})
            except Failure as failure:
                if "vendorCode" not in object_value(failure.result.get("detail")) or cancellation.aborted:
                    raise
                turn_input = labelled_history_input(request.history, request.input)
                pending_notices.append(
                    {
                        "code": "history_as_text",
                        "message": "Codex refused the native history; the earlier conversation was sent as labelled text.",
                    }
                )
        message = prepare_turn_input(turn_input, temporary)
        startup = [
            notice for notice in server.take_notifications() if notice.method in ("warning", "deprecationNotice")
        ]
        turn = object_value(
            await rpc(
                "turn/start",
                {
                    "threadId": conversation,
                    "input": message,
                    "model": model["id"],
                    "effort": effort,
                    "summary": "detailed",
                    "approvalPolicy": "never",
                    "sandboxPolicy": {"type": "readOnly", "networkAccess": False}
                    if request.tools == "none"
                    else {"type": "dangerFullAccess"},
                    **({"serviceTier": request.service_tier} if request.service_tier is not None else {}),
                },
            )
        )
        turn_id = string(object_value(turn.get("turn")).get("id"))
        if turn_id is None:
            raise Failure("tool_failed", "Codex returned a malformed turn.")

        def emit(type_: str, data: Object) -> None:
            if type_ == "text" and "parentCallId" not in data:
                fingerprint.add({"type": "message", "role": "assistant", "text": data["text"]})
            events.emit(type_, data)

        mapper = RunEvents(conversation, turn_id, current_model, emit)
        write_json(
            temporary / "shell-owners.json", [owner_json(owner) for owner in await server.capture_process_groups()]
        )
        events.emit(
            "started",
            {
                "continuity": plan["continuity"],
                **({"rebuildReason": plan["rebuildReason"]} if "rebuildReason" in plan else {}),
                "subscriptionId": request.subscription_id,
                "model": current_model,
                **({"effort": effort} if effort is not None else {}),
                "toolVersion": server.tool_version or tool["version"],
                "driverBuild": build,
            },
        )
        started = True
        for notice in startup:
            mapper.consume(notice.method, notice.params)
        for request_notice in [*pending_notices, *subscriptions.notices]:
            events.emit("notice", request_notice)
        await events.flush(cancellation)
        remaining_calls_deadline: float | None = None
        while mapper.outcome is None or mapper.calls or mapper.waiting_for_work:
            waiting_for_other = mapper.outcome is not None and not mapper.waiting_for_work
            if waiting_for_other and remaining_calls_deadline is None:
                remaining_calls_deadline = time.monotonic() + fixed_wait(2000, env)
            remaining = None if remaining_calls_deadline is None else remaining_calls_deadline - time.monotonic()
            if waiting_for_other and remaining is not None and remaining <= 0:
                break
            try:
                notice = await server.next_notification(
                    cancellation=cancellation, timeout=remaining if waiting_for_other else None
                )
            except Failure as failure:
                if waiting_for_other and "Timed out" in str(failure):
                    break
                raise
            params = object_value(notice.params)
            if (
                plan["continuity"] == "resumed"
                and notice.method == "thread/tokenUsage/updated"
                and params.get("threadId") == conversation
                and ("turnId" not in params or params["turnId"] in restored_turns)
            ):
                continue
            if notice.method == "item/started" and object_value(params.get("item")).get("type") == "commandExecution":
                write_json(
                    temporary / "shell-owners.json",
                    [owner_json(owner) for owner in await server.capture_process_groups()],
                )
            mapper.consume(notice.method, notice.params)
            await events.flush(cancellation)
        if mapper.outcome == "failed":
            error = Failure(
                str((mapper.error or {}).get("code", "vendor_error")),
                str((mapper.error or {}).get("message", "Codex failed the turn.")),
                mapper.error,
            )
        elif mapper.outcome == "interrupted":
            error = Failure("tool_failed", "Codex interrupted the turn without a caller stop.")
    except Exception as failure:
        error = failure
    finally:
        if cancellation.aborted and server is not None:
            if mapper is None and conversation is not None:
                queued = server.take_notifications()
                announced = next(
                    (
                        notice
                        for notice in queued
                        if notice.method == "turn/started"
                        and object_value(notice.params).get("threadId") == conversation
                        and isinstance(object_value(object_value(notice.params).get("turn")).get("id"), str)
                    ),
                    None,
                )
                if announced is not None:
                    mapper = RunEvents(
                        conversation,
                        str(object_value(object_value(announced.params).get("turn"))["id"]),
                        current_model or "",
                        events.emit,
                    )
                    if not started and request is not None and plan is not None:
                        events.emit(
                            "started",
                            {
                                "continuity": plan["continuity"],
                                **({"rebuildReason": plan["rebuildReason"]} if "rebuildReason" in plan else {}),
                                "subscriptionId": request.subscription_id,
                                "model": current_model,
                                "toolVersion": server.tool_version,
                                "driverBuild": build,
                            },
                        )
                    for notice in queued:
                        mapper.consume(notice.method, notice.params)
            if mapper is not None:
                try:
                    await interrupt_turns(
                        server, mapper, (cancellation.stopped_at or time.monotonic()) + fixed_wait(2000, env)
                    )
                except Exception:
                    pass
        if server is not None:

            async def stop_during_end() -> None:
                await cancellation.event.wait()
                assert server is not None
                stopped = cancellation.stopped_at or time.monotonic()
                await server.close(stopped + fixed_wait(15000, env), stopped + fixed_wait(2000, env))

            end_stop = asyncio.create_task(stop_during_end())
            try:
                stopped = cancellation.stopped_at
                await server.end(
                    None if stopped is None else stopped + fixed_wait(15000, env),
                    None if stopped is None else stopped + fixed_wait(2000, env),
                )
            except Exception as failure:
                error = error or failure
                if cancellation.aborted:
                    events.emit("notice", {"code": "cleanup_failed", "message": str(failure)})
            finally:
                end_stop.cancel()
                await asyncio.gather(end_stop, return_exceptions=True)
        settled = True
        if input_ is not None:
            input_.close()
        if control_task is not None:
            control_task.cancel()
            await asyncio.gather(control_task, return_exceptions=True)
        if mapper is not None:
            mapper.close_open_calls(
                "The tool call was interrupted by the caller."
                if cancellation.aborted
                else "The run ended before the tool call finished."
            )
        if temporary is not None:
            try:
                shutil.rmtree(temporary)
            except OSError as failure:
                error = error or failure
    if request is not None and plan is not None and reserved_id is not None:
        try:
            await events.flush(cancellation)
        except Exception as failure:
            error = error or failure
        try:
            await chats.settle(
                request,
                plan,
                conversation,
                fingerprint.snapshot(),
                error is None and not cancellation.aborted and mapper is not None and mapper.outcome == "completed",
            )
        except Exception as failure:
            error = error or failure
    try:
        finish = asyncio.create_task(
            events.finish(
                error,
                cancellation.aborted,
                {
                    "producedOutput": mapper.output_produced if mapper is not None else False,
                    "unfinishedCalls": mapper.unfinished_calls if mapper is not None else [],
                    **({"usage": mapper.usage} if mapper is not None else {}),
                },
            )
        )

        async def output_deadline() -> int:
            await cancellation.event.wait()
            await asyncio.sleep(
                max(0.001, (cancellation.stopped_at or time.monotonic()) + fixed_wait(15000, env) - time.monotonic())
            )
            events.abandon()
            return 2

        deadline_task = asyncio.create_task(output_deadline())
        try:
            done, _ = await asyncio.wait({finish, deadline_task}, return_when=asyncio.FIRST_COMPLETED)
            code = next(iter(done)).result()
        finally:
            deadline_task.cancel()
            if not finish.done():
                finish.cancel()
            await asyncio.gather(finish, deadline_task, return_exceptions=True)
        if (
            code != 0
            and request is not None
            and plan is not None
            and reserved_id is not None
            and conversation is not None
        ):
            await chats.settle(
                request, {**plan, "continuedConversation": conversation}, conversation, fingerprint.snapshot(), False
            )
        return code
    except Exception:
        if request is not None and plan is not None and reserved_id is not None and conversation is not None:
            await chats.settle(
                request, {**plan, "continuedConversation": conversation}, conversation, fingerprint.snapshot(), False
            )
        return 2 if cancellation.aborted else 1
    finally:
        events.output.on_error = None
        if reserved_id is not None:
            runs.remove(reserved_id)
