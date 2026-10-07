import asyncio
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Protocol, cast

from .cancellation import Cancellation, interruptible
from .environment import clean_environment
from .errors import Failure
from .json_types import Object, iso, now
from .process_groups import force_process_groups
from .state import Owner, State, private_directory, read_json, write_json

OLDEST_SUPPORTED = "0.159.2"


class ChildTransport(Protocol):
    _transport: asyncio.SubprocessTransport


def supported_version(version: str) -> bool:
    return re.fullmatch(r"\d+\.\d+\.\d+", version) is not None and tuple(map(int, version.split("."))) >= tuple(
        map(int, OLDEST_SUPPORTED.split("."))
    )


def find_tool(tool_path: str | None, env: dict[str, str]) -> str | None:
    program = tool_path or "codex"
    candidates = (
        [Path(program).absolute()]
        if "/" in program or "\\" in program
        else [Path(folder or ".").absolute() / program for folder in env.get("PATH", "").split(os.pathsep)]
    )
    return next((str(path) for path in candidates if path.is_file() and os.access(path, os.X_OK)), None)


async def version_output(path: str, env: dict[str, str], home: Path, cancellation: Cancellation | None) -> str:
    child = await asyncio.create_subprocess_exec(
        path,
        "--version",
        env=env,
        cwd=home,
        start_new_session=True,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    assert child.stdout is not None
    output = bytearray()

    owner: Owner = {"pid": child.pid, "startedAt": now()}

    async def kill() -> None:
        await force_process_groups([owner], asyncio.get_running_loop().time() + 1)

    async def drain() -> None:
        assert child.stdout is not None
        while chunk := await child.stdout.read(4096):
            output.extend(chunk)
            if len(output) > 16384:
                raise ValueError("Oversized version")

    async def completed() -> None:
        while child.returncode is None:
            await asyncio.sleep(0.005)
        await kill()  # Descendants holding stdout are also ended.
        await child.wait()

    try:

        async def query() -> None:
            await asyncio.gather(drain(), completed())

        await interruptible(query(), cancellation, 10)
        if child.returncode != 0:
            raise ValueError("Version failed")
        return output.decode("utf-8", "replace")
    finally:
        try:
            await kill()
        finally:
            cast(ChildTransport, child)._transport.close()
            try:
                await asyncio.wait_for(child.wait(), 0.5)
            except TimeoutError:
                pass


async def inspect_tool(
    state: State, tool_path: str | None, env: dict[str, str], cancellation: Cancellation | None = None
) -> Object:
    info: Object = {"name": "codex", "supported": False, "oldestSupported": OLDEST_SUPPORTED}
    path = find_tool(tool_path, env)
    if path is None:
        return info
    info["path"] = path
    metadata = Path(path).stat()
    changed_at = iso(metadata.st_mtime)
    cached = read_json(state.directory / "tool.json")
    if (
        isinstance(cached, dict)
        and cached.get("path") == path
        and cached.get("size") == metadata.st_size
        and cached.get("changedAt") == changed_at
        and isinstance(cached.get("version"), str)
        and re.fullmatch(r"\d+\.\d+\.\d+", str(cached["version"]))
    ):
        version = str(cached["version"])
    else:
        temporary = state.directory / "tmp"
        private_directory(temporary)
        home = Path(tempfile.mkdtemp(prefix="version-", dir=temporary))
        try:
            try:
                output = await version_output(
                    path, clean_environment(env, str(home), str(home / ".codex")), home, cancellation
                )
            except FileNotFoundError:
                raise Failure(
                    "tool_missing",
                    f"codex was not found; version not found, needed {OLDEST_SUPPORTED}.",
                    {"detail": {"basis": "fields", "neededVersion": OLDEST_SUPPORTED}, "remedy": "Install codex."},
                ) from None
            except (OSError, ValueError, TimeoutError, Failure):
                raise Failure(
                    "tool_failed",
                    f"codex could not report its version at {path}.",
                    {"detail": {"basis": "fields", "neededVersion": OLDEST_SUPPORTED}},
                ) from None
            match = re.fullmatch(r"\s*codex-cli\s+(\d+\.\d+\.\d+)\s*", output)
            if match is None:
                raise Failure(
                    "tool_failed",
                    "codex returned an unrecognised version record.",
                    {"detail": {"basis": "fields", "neededVersion": OLDEST_SUPPORTED}},
                )
            version = match[1]
            write_json(
                state.directory / "tool.json",
                {"path": path, "size": metadata.st_size, "changedAt": changed_at, "version": version, "askedAt": now()},
            )
        finally:
            shutil.rmtree(home, ignore_errors=True)
    info.update(version=version, supported=supported_version(version))
    return info


def require_tool(tool: Object) -> str:
    if not isinstance(tool.get("path"), str):
        raise Failure(
            "tool_missing",
            f"codex was not found; version not found, needed {OLDEST_SUPPORTED}.",
            {"detail": {"basis": "fields", "neededVersion": OLDEST_SUPPORTED}, "remedy": "Install codex."},
        )
    if not tool.get("supported"):
        version = tool.get("version", "unknown")
        raise Failure(
            "tool_unsupported",
            f"codex {version} is unsupported; needed {OLDEST_SUPPORTED} or newer.",
            {
                "detail": {"basis": "fields", "toolVersion": version, "neededVersion": OLDEST_SUPPORTED},
                "remedy": "Update codex.",
            },
        )
    return str(tool["path"])
