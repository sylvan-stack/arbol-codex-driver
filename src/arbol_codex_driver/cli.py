import asyncio
import os
import signal
import sys
from contextlib import ExitStack
from pathlib import Path
from typing import cast

from .admission import current_session, standalone_launch
from .arguments import Options, parse_arguments
from .build import build_identity, qualified_capabilities
from .cancellation import Cancellation
from .errors import Failure, safe_failure
from .event_stream import EventStream, Output, write_json
from .identity_protocol import invalid
from .json_types import Json, string
from .maintenance import current_maintenance
from .run import run
from .runs import Runs
from .settings import read_settings, settings_path
from .state import State, default_state_directory, fixed_wait, prepare_default_state
from .state_upgrade import Operation
from .subscriptions import FAMILIES, Subscriptions
from .tool import inspect_tool, require_tool


class Invocation:
    """Owned by synchronous entry until asyncio.run joins tasks and executor."""

    def __init__(self) -> None:
        self.state: State | None = None
        self.contexts = ExitStack()

    def close(self) -> None:
        try:
            self.contexts.close()
        finally:
            if self.state is not None:
                self.state.close()


async def main(args: list[str], *, invocation: Invocation | None = None) -> int:
    # Direct asynchronous callers may retain this object until their own loop
    # settles. No destructor releases a guard when its lexical scope ends.
    invocation = Invocation() if invocation is None else invocation
    output = Output()
    operation = next(
        (
            arg
            for index, arg in enumerate(args)
            if arg != "--state-dir"
            and (index == 0 or args[index - 1] != "--state-dir")
            and not arg.startswith("--state-dir=")
        ),
        None,
    )
    events = EventStream(output) if operation == "run" else None
    cancellation = Cancellation()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, cancellation.abort)
    try:
        command = parse_arguments(args)
        if command.name.startswith("state "):
            maintenance = current_maintenance()
            maintenance.recheck()
            request = maintenance.request
            expected: Options = {
                "state-dir": str(request.state), "maintenance": str(request.receipt),
                "backup": str(request.backup), "confirm-quiescent": True,
            }
            if request.operation == "upgrade":
                expected["from-format"] = "1"
            if request.source is not None:
                expected["source"] = str(request.source)
            if request.subscription is not None:
                expected.update({"subscription": request.subscription, "retire": True})
            if command.name != "state " + request.operation or command.options != expected:
                raise invalid()
            administration = invocation.contexts.enter_context(Operation(maintenance))
            match request.operation:
                case "upgrade":
                    administrative_result = await administration.upgrade()
                case "identity-reset":
                    administrative_result = await administration.reset()
                case "identity-recover":
                    administrative_result = await administration.recover()
                case "restore":
                    administrative_result = await administration.restore()
                case _:
                    raise invalid()
            cancellation.check()
            await write_json(output, administrative_result)
            return 0
        if not standalone_launch.get():
            current_session()
        if command.name == "dev stand-in":
            from .stand_in import stand_in

            return await stand_in(Path(command.positionals[0]).absolute(), command.positionals[2:], output)
        fixed_wait(1)
        home = os.environ.get("HOME") or str(Path.home())
        file = settings_path(home)
        env = dict(os.environ)
        default = default_state_directory(home)
        state = State(string(command.options.get("state-dir")) or default)
        if state.directory == Path(os.path.abspath(default)):
            prepare_default_state(home)
        invocation.state = state
        if command.name == "subscriptions identity":
            # Proof is independent of settings, run recovery, get/reap and
            # native account discovery, including on signed-out chatgpt.
            state.initialize()
            proof = await Subscriptions(state, {}, [], file, env, cancellation).identity(
                command.positionals[0], string(command.options.get("expect")),
            )
            cancellation.check()
            await write_json(output, proof)
            return 0
        settings, notices = read_settings(file)
        state.initialize()
        if command.name in (
            "subscriptions update",
            "subscriptions sign-in",
            "subscriptions check",
            "subscriptions usage",
            "subscriptions models",
        ):
            await Runs(state).list()
        identity = build_identity()
        cancellation.check()
        if command.name == "run":
            assert events is not None
            return await run(
                command,
                Subscriptions(state, settings, notices, file, env, cancellation),
                events,
                env,
                str(identity["build"]),
                cancellation,
            )
        if command.name == "runs list":
            records: list[Json] = [
                {
                    key: value
                    for key, value in record.items()
                    if key in ("runId", "subscriptionId", "startedAt", "labels")
                }
                for record in await Runs(state).list()
            ]
            await write_json(output, records)
            return 0
        if command.name == "runs stop":
            await Runs(state).stop(command.positionals[0])
            return 0
        if command.name in ("dev probe", "dev live-check", "dev build-check"):
            from .dev import live_check, probe

            subscriptions = Subscriptions(state, settings, notices, file, env, cancellation)
            status, report = (
                await probe(subscriptions, env, cancellation)
                if command.name == "dev probe"
                else await live_check(command.name == "dev build-check", subscriptions, env, cancellation)
            )
            await write_json(output, report)
            return status
        if command.name == "info":
            tool = await inspect_tool(state, string(settings.get("toolPath")), env, cancellation)
            cancellation.check()
            await write_json(
                output,
                {
                    "driver": "codex",
                    **identity,
                    "contract": 1,
                    "capabilities": {**qualified_capabilities(), "cueContext": 1},
                    "stateDirectory": str(state.directory),
                    "settingsFile": str(file),
                    "tool": tool,
                    **({"notices": cast(list[Json], notices)} if notices else {}),
                },
            )
            return 0
        if command.name.startswith("subscriptions "):
            subscriptions = Subscriptions(state, settings, notices, file, env, cancellation)
            id_ = command.positionals[0] if command.positionals else ""
            result: Json
            match command.name:
                case "subscriptions families":
                    result = FAMILIES
                case "subscriptions list":
                    result = await subscriptions.list()
                case "subscriptions create":
                    result = await subscriptions.create(
                        command.options.get("family"), command.options.get("label"), string(command.options.get("id"))
                    )
                case "subscriptions update":
                    result = await subscriptions.update(id_, string(command.options.get("label")))
                case "subscriptions remove":
                    await subscriptions.remove(id_, command.options.get("force") is True)
                    return 0
                case "subscriptions sign-in":
                    return await subscriptions.sign_in(
                        id_, command.options.get("by-code") is True, lambda value: write_json(output, value)
                    )
                case "subscriptions sign-out":
                    result = await subscriptions.sign_out(id_, command.options.get("force") is True)
                case "subscriptions check":
                    result = await subscriptions.check(id_)
                case "subscriptions usage":
                    result = await subscriptions.usage(id_)
                case "subscriptions models":
                    result = await subscriptions.models(id_)
                case _:
                    raise Failure("unsupported", "This Subscription command is not supported by the Codex Driver.")
            cancellation.check()
            if notices and isinstance(result, dict):
                result = {**result, "notices": cast(list[Json], notices)}
            await write_json(output, result)
            return 0
        if command.tool_required:
            require_tool(await inspect_tool(state, string(settings.get("toolPath")), env, cancellation))
        raise Failure("unsupported", f"Command {command.name} is not implemented in this Driver yet.")
    except Exception as error:
        if events is not None:
            try:
                return await events.finish(error, cancellation.aborted)
            except OSError:
                return 2
        if cancellation.aborted:
            return 2
        await write_json(output, {"error": safe_failure(error)})
        return 1
    finally:
        for signum in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(signum)


def entry(*, standalone: bool = True) -> None:
    invocation = Invocation()
    token = standalone_launch.set(standalone)
    try:
        code = asyncio.run(main(sys.argv[1:], invocation=invocation))
    finally:
        # asyncio.run has joined every remaining task and executor worker;
        # component authority is still retained by the outer trusted entry.
        try:
            invocation.close()
        finally:
            standalone_launch.reset(token)
    sys.exit(code)
