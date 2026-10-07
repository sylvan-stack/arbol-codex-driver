import asyncio
import os
import signal
import sys
from pathlib import Path
from typing import cast

from .arguments import parse_arguments
from .build import build_identity
from .cancellation import Cancellation
from .errors import Failure, safe_failure
from .event_stream import EventStream, Output, write_json
from .json_types import Json, string
from .run import run
from .runs import Runs
from .settings import read_settings, settings_path
from .state import State, default_state_directory, fixed_wait
from .subscriptions import FAMILIES, Subscriptions
from .tool import inspect_tool, require_tool


async def main(args: list[str]) -> int:
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
        if command.name == "dev stand-in":
            from .stand_in import stand_in

            return await stand_in(Path(command.positionals[0]).absolute(), command.positionals[2:], output)
        fixed_wait(1)
        home = os.environ.get("HOME") or str(Path.home())
        file = settings_path(home)
        settings, notices = read_settings(file)
        env = dict(os.environ)
        state = State(string(command.options.get("state-dir")) or default_state_directory(home))
        state.initialize()
        if command.name in (
            "subscriptions create",
            "subscriptions update",
            "subscriptions remove",
            "subscriptions sign-in",
            "subscriptions sign-out",
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
        if command.name == "info":
            tool = await inspect_tool(state, string(settings.get("toolPath")), env, cancellation)
            cancellation.check()
            await write_json(
                output,
                {
                    "driver": "codex",
                    **identity,
                    "contract": 1,
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


def entry() -> None:
    sys.exit(asyncio.run(main(sys.argv[1:])))
