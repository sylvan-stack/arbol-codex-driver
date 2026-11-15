import asyncio
import math
import os
import re
import stat
import subprocess
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict, cast

from .errors import Failure
from .identity import DATA_FORMAT as DATA_FORMAT
from .identity import IdentityState
from .json_types import Json, dumps, iso, loads, timestamp


class Owner(TypedDict):
    pid: int
    startedAt: str


def default_state_directory(home: str) -> Path:
    return Path(home) / "Library" / "Application Support" / "Arbol" / "drivers" / "codex"


def fixed_wait(milliseconds: float, env: dict[str, str] | None = None) -> float:
    source = os.environ if env is None else env
    raw = source.get("ARBOL_TEST_TIME_SCALE")
    if raw is None:
        return milliseconds / 1000
    try:
        scale = float(raw.strip() or "0")
    except ValueError:
        scale = 0
    if not math.isfinite(scale) or scale <= 0:
        raise Failure("invalid_input", "ARBOL_TEST_TIME_SCALE must be a positive finite number.")
    return milliseconds / (1000 * scale)


def private_directory(path: Path) -> None:
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    path.chmod(0o700)


def remove_file(path: Path) -> None:
    path.unlink(missing_ok=True)


def prepare_file(path: Path, content: str) -> Path:
    private_directory(path.parent)
    temporary = path.parent / (".write-" + str(uuid.uuid4()))
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
    except BaseException:
        remove_file(temporary)
        raise
    return temporary


def atomic_write(path: Path, content: str) -> None:
    temporary = prepare_file(path, content)
    try:
        os.replace(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        remove_file(temporary)


def write_json(path: Path, value: Json) -> None:
    atomic_write(path, dumps(value) + "\n")


def read_json(path: Path) -> Json:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise ValueError("State JSON is not a regular file")
            # Keep the legacy text decoder/JSON grammar and unrestricted record
            # size. The independent descriptor is closed even if wrapping fails.
            with os.fdopen(descriptor, "r", closefd=False) as file:
                value = loads(file.read())
        finally:
            os.close(descriptor)
        if value is None:
            raise ValueError("Null state record")
        return value
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        raise Failure("internal", f"Cannot read state file {path}.") from None


def parse_owner(value: Json) -> Owner:
    if (
        not isinstance(value, dict)
        or type(value.get("pid")) is not int
        or cast(int, value["pid"]) <= 0
        or timestamp(value.get("startedAt")) is None
    ):
        raise Failure("internal", "A process owner record is malformed.")
    return {"pid": cast(int, value["pid"]), "startedAt": cast(str, value["startedAt"])}


def owner_json(owner: Owner) -> dict[str, Json]:
    return {"pid": owner["pid"], "startedAt": owner["startedAt"]}


def ps_time(raw: str) -> str:
    try:
        return iso(datetime.strptime(raw.strip(), "%a %b %d %H:%M:%S %Y").replace(tzinfo=UTC).timestamp())
    except ValueError:
        raise Failure("internal", "Cannot read a process start time.") from None


async def process_owner(pid: int) -> Owner | None:
    if type(pid) is not int or pid <= 0:
        raise Failure("internal", "A process identifier is malformed.")

    def query() -> Owner | None:
        try:
            answer = subprocess.run(
                ["/bin/ps", "-p", str(pid), "-o", "lstart="],
                env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "TZ": "UTC"},
                capture_output=True,
                text=True,
                timeout=5,
            )
            if answer.returncode == 1:
                return None
            if answer.returncode != 0:
                raise ValueError
            return {"pid": pid, "startedAt": ps_time(answer.stdout)}
        except (OSError, ValueError, subprocess.TimeoutExpired):
            raise Failure("internal", f"Cannot read the start time of process {pid}.") from None

    return await asyncio.to_thread(query)


async def owner_alive(owner: Owner) -> bool:
    parse_owner(owner_json(owner))
    current = await process_owner(owner["pid"])
    return (
        current is not None
        and abs(cast(float, timestamp(current["startedAt"])) - cast(float, timestamp(owner["startedAt"]))) <= 2
    )


def read_lock(path: Path) -> tuple[os.stat_result, Owner] | None:
    try:
        with path.open() as file:
            snapshot = os.fstat(file.fileno())
            value = loads(file.read())
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        raise Failure("internal", f"Malformed lock {path}.") from None
    if not isinstance(value, dict):
        raise Failure("internal", f"Malformed lock {path}.")
    return snapshot, parse_owner(value.get("owner"))


async def reclaim_dead_file(path: Path, snapshot: os.stat_result, temporary: Path) -> None:
    election = path.parent / f".write-reap-{snapshot.st_ino}"
    elected = False
    try:
        os.link(temporary, election)
        elected = True
        try:
            current = path.stat()
        except FileNotFoundError:
            return
        if current.st_ino == snapshot.st_ino and current.st_dev == snapshot.st_dev:
            remove_file(path)
    except FileExistsError:
        reaper = read_lock(election)
        if reaper is not None and not await owner_alive(reaper[1]):
            await reclaim_dead_file(election, reaper[0], temporary)
    except FileNotFoundError:
        pass
    finally:
        if elected:
            remove_file(election)


class State:
    def __init__(self, directory: Path | str) -> None:
        self.directory = Path(os.path.abspath(directory))
        self.identity: IdentityState | None = None

    def initialize(self) -> None:
        if self.identity is None:
            self.identity = IdentityState.open(self.directory)
        else:
            self.identity.check()

    def assert_admitted(self) -> IdentityState:
        if self.identity is None:
            raise Failure("internal", "Driver state has not been admitted.")
        self.identity.check()
        return self.identity

    def close(self) -> None:
        if self.identity is not None:
            self.identity.close()

    def subscription(self, id_: str) -> Path:
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}", id_):
            raise Failure("invalid_input", "The Subscription identifier is not a safe file name.")
        self.assert_admitted()
        return self.directory / "subscriptions" / id_

    def clear_unfinished_writes(self) -> None:
        self.assert_admitted()
        def visit(directory: Path, depth: int) -> None:
            if not directory.exists():
                return
            for entry in directory.iterdir():
                if entry.is_symlink():
                    continue
                if entry.is_file() and entry.name.startswith(".write-"):
                    try:
                        if time.time() - entry.stat().st_mtime > 60:
                            remove_file(entry)
                    except FileNotFoundError:
                        pass
                elif depth and entry.is_dir() and entry.name not in ("home", "tmp"):
                    visit(entry, depth - 1)

        visit(self.directory, 3)

    async def with_subscription_lock[T](
        self, id_: str, change: Callable[[], Awaitable[T]], env: dict[str, str] | None = None
    ) -> T:
        directory = self.subscription(id_)
        return await with_subscription_directory_lock(directory, change, env)


async def with_subscription_directory_lock[T](
    directory: Path, change: Callable[[], Awaitable[T]], env: dict[str, str] | None = None,
) -> T:
    """Existing canonical lock; caller establishes normal or exclusive admission."""
    timeout, retry = fixed_wait(10000, env), fixed_wait(50, env)
    private_directory(directory.parent)
    private_directory(directory)
    path = directory / "lock"
    owner = await process_owner(os.getpid())
    if owner is None:
        raise Failure("internal", "Cannot identify the Driver process.")
    temporary = prepare_file(path, dumps({"owner": owner_json(owner)}) + "\n")
    deadline = time.monotonic() + timeout
    acquired = False
    try:
        while not acquired:
            try:
                os.link(temporary, path)
                acquired = True
            except FileExistsError:
                existing = read_lock(path)
                if existing is None:
                    continue
                if not await owner_alive(existing[1]):
                    await reclaim_dead_file(path, existing[0], temporary)
                if time.monotonic() >= deadline:
                    raise Failure(
                        "internal",
                        f"Subscription lock timed out after {timeout * 1000:g} milliseconds; owner PID {existing[1]['pid']}, started {existing[1]['startedAt']}.",
                    ) from None
                await asyncio.sleep(retry)
        return await change()
    finally:
        if acquired:
            remove_file(path)
        remove_file(temporary)
