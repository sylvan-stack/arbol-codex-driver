import asyncio
import codecs
import fcntl
import json
import math
import os
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast

from .admission import current_session
from .build import build_identity
from .cancellation import Cancellation, interruptible
from .environment import clean_environment
from .errors import Failure, safe_text
from .identity_protocol import PrivateDirectory
from .json_types import Json, Object, dumps, loads, object_value, string
from .owner_setup import DiagnosticScrubber, sanitize_diagnostic
from .process_groups import collect_process_groups, end_process_groups, force_process_groups
from .process_identity import matches as admission_matches
from .process_identity import process_identity as admission_process_identity
from .state import Owner, fixed_wait, owner_json, private_directory, process_owner, ps_time
from .tool import OLDEST_SUPPORTED, supported_version

APP_SERVER_OPTIONS: tuple[str, ...] = ()


# The shell reads only the private pipe, closes its inherited barrier, then
# execs the exact existing positional vendor argv. It never writes Driver state.
_EXEC_BARRIER = (
    'barrier="$1"; shift; case "$barrier" in ""|*[!0-9]*) exit 1;; esac; '
    'IFS= read -r release <&"$barrier" || exit 1; [ "$release" = go ] || exit 1; '
    'eval "exec ${barrier}<&-"; exec "$@"'
)


def startup_ledger(owner: Owner) -> bytes:
    """Retain the existing PID + C-locale lstart reader, without float time."""
    value = datetime.fromisoformat(owner["startedAt"]).astimezone(UTC)
    days = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
    months = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
    line = (f"{days[value.weekday()]} {months[value.month - 1]} {value.day:2d} "
            f"{value.hour:02d}:{value.minute:02d}:{value.second:02d} {value.year:04d}")
    if ps_time(line) != owner["startedAt"]:
        raise Failure("internal", "Cannot preserve the tool process identity.")
    return f"{owner['pid']}\n{line}\n".encode("ascii")


def rpc_failure(error: Object, private_values: tuple[str, ...] = ()) -> Failure:
    message = str(error["message"])
    data = object_value(error.get("data"))
    status = data.get("httpStatusCode")
    if not isinstance(status, (int, float)):
        status = error.get("code") if error.get("code") in (401, 403) else None
    structured = (
        status in (401, 403)
        or error.get("code") in ("unauthorized", "credential_rejected")
        or data.get("codexErrorInfo") == "unauthorized"
    )
    wording = bool(
        re.search(
            r"codex account authentication required to read (?:rate limits|token usage)|not logged in|logged out|codex login|invalid api key|missing credentials|please login|please log in|chatgpt login expired",
            message,
            re.I,
        )
    )
    detail: Object = {"basis": "wording" if not structured and wording else "fields"}
    if status is not None:
        detail["vendorStatus"] = status
    if isinstance(error.get("code"), (str, int, float)):
        detail["vendorCode"] = str(error["code"])
    return Failure(
        "credential_rejected" if structured or wording else "tool_failed",
        safe_text(message, private_values, None),
        object_value(
            sanitize_diagnostic(
                {"detail": detail, **({"remedy": "Sign in directly in Codex."} if structured or wording else {})},
                private_values,
            )
        ),
    )


@dataclass
class Notification:
    method: str
    params: Json
    size: int = 0


class ChildTransport(Protocol):
    _transport: asyncio.SubprocessTransport


class AppServer:
    def __init__(
        self,
        child: asyncio.subprocess.Process,
        owner: Owner,
        timeout: float,
        cleanup_grace: float,
        on_server_request: Callable[[str, Json], Json] | None,
        private_values: tuple[str, ...] = (),
        on_notification: Callable[[str, Json], None] | None = None,
    ) -> None:
        self.child, self.owner, self.timeout, self.cleanup_grace = child, owner, timeout, cleanup_grace
        self.on_server_request = on_server_request
        self.private_values = private_values
        self.on_notification = on_notification
        self.last_notification_at = time.monotonic()
        self.next_id = 1
        self.pending: dict[int, asyncio.Future[Json]] = {}
        self.notifications: list[Notification] = []
        self.notification_bytes = 0
        self.notification_space = asyncio.Event()
        self.watchers: list[tuple[str, Callable[[Json], bool], asyncio.Future[Json]]] = []
        self.notification_waiter: asyncio.Future[Notification] | None = None
        self.failure: Failure | None = None
        self.tool_version: str | None = None
        self.log_tail = ""
        self.groups: dict[int, Owner] = {owner["pid"]: owner}
        self.closing: asyncio.Task[None] | None = None
        self.ending: asyncio.Task[None] | None = None
        self.tasks = [
            asyncio.create_task(self.read_stdout()),
            asyncio.create_task(self.read_stderr()),
            asyncio.create_task(self.monitor()),
        ]
        self.background: set[asyncio.Task[None]] = set()

    @classmethod
    async def start(
        cls,
        *,
        tool_path: str,
        home: Path | None,
        env: dict[str, str],
        arbol_chat_id: str | None = None,
        disabled_hook_features: tuple[str, ...] = (),
        cwd: Path | None = None,
        cancellation: Cancellation | None = None,
        request_timeout: float = 30,
        on_spawn: Callable[[Owner], Awaitable[None]] | None = None,
        on_server_request: Callable[[str, Json], Json] | None = None,
        launch_identity_path: Path | None = None,
        private_values: tuple[str, ...] = (),
        on_notification: Callable[[str, Json], None] | None = None,
    ) -> AppServer:
        if cancellation is not None:
            cancellation.check()
        if not math.isfinite(request_timeout) or request_timeout <= 0:
            raise Failure("invalid_input", "The app-server request timeout must be a positive finite number.")
        owner_home = env.get("HOME") or str(Path.home())
        isolated_home = home.absolute() if home is not None else None
        home = isolated_home if isolated_home is not None else Path(owner_home) / ".codex"
        if isolated_home is not None:
            private_directory(isolated_home)
        identity = build_identity()
        arguments = [tool_path, "app-server", *APP_SERVER_OPTIONS]
        barrier_read, barrier_write = -1, -1

        def close_barrier() -> None:
            nonlocal barrier_read, barrier_write
            owned = (barrier_read, barrier_write)
            barrier_read, barrier_write = -1, -1
            for descriptor in owned:
                if descriptor >= 0:
                    os.close(descriptor)

        if launch_identity_path is not None:
            session = current_session()
            with session.registry.mutex():
                session._check()
            raw_read, raw_write = os.pipe()
            try:
                # Keep the private barrier distinct from child stdio even if
                # the caller originally closed descriptor 0, 1 or 2.
                barrier_read = fcntl.fcntl(raw_read, fcntl.F_DUPFD_CLOEXEC, 3)
                barrier_write = fcntl.fcntl(raw_write, fcntl.F_DUPFD_CLOEXEC, 3)
            except BaseException:
                close_barrier()
                raise
            finally:
                os.close(raw_read)
                os.close(raw_write)
            arguments = ["/bin/sh", "-c", _EXEC_BARRIER, "arbol-codex-launch", str(barrier_read), *arguments]
        # The clean environment excludes inherited Arbol identity.
        child_env = clean_environment(env, owner_home, str(isolated_home) if isolated_home is not None else None)
        if "SHELL" in env:
            child_env["SHELL"] = env["SHELL"]
        if arbol_chat_id is not None:
            child_env["ARBOL_CHAT"] = arbol_chat_id
            if disabled_hook_features:
                child_env["ARBOL_DISABLED_HOOK_FEATURES"] = ",".join(disabled_hook_features)
        try:
            child = await asyncio.create_subprocess_exec(
                *arguments,
                cwd=cwd or (home if isolated_home is not None else Path(owner_home)),
                env=child_env,
                start_new_session=True,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                pass_fds=(barrier_read,) if barrier_read >= 0 else (),
                close_fds=True,
            )
            if barrier_read >= 0:
                descriptor, barrier_read = barrier_read, -1
                os.close(descriptor)
        except BaseException as error:
            close_barrier()
            if isinstance(error, OSError):
                raise Failure("tool_failed", "Cannot start the codex app-server.") from None
            raise
        from .json_types import now

        server = cls(
            child,
            {"pid": child.pid, "startedAt": now()},
            request_timeout,
            fixed_wait(500, env),
            on_server_request,
            private_values,
            on_notification,
        )
        try:
            owner = await process_owner(child.pid)
            if owner is None:
                raise Failure("tool_failed", "Cannot identify the codex app-server process.")
            blocked_identity = admission_process_identity(child.pid) if launch_identity_path is not None else None
            server.owner = owner
            server.groups[owner["pid"]] = owner
            if launch_identity_path is not None:
                assert blocked_identity is not None
                if (
                    not admission_matches(blocked_identity, parent=os.getpid())
                    or await process_owner(child.pid) != owner or child.returncode is not None
                ):
                    raise Failure("tool_failed", "The app-server startup process changed.")
                with PrivateDirectory(launch_identity_path.parent) as directory:
                    directory.publish(launch_identity_path.name, startup_ledger(owner))
            if on_spawn is not None:
                await on_spawn(owner)
            if launch_identity_path is not None:
                assert blocked_identity is not None
                if cancellation is not None:
                    cancellation.check()
                if (
                    not admission_matches(blocked_identity, parent=os.getpid())
                    or await process_owner(child.pid) != owner or child.returncode is not None
                ):
                    raise Failure("tool_failed", "The app-server startup process changed.")
                current_session().registry.check_lock("admission.lock", current_session().lease)
                if os.write(barrier_write, b"go\n") != 3:
                    raise Failure("tool_failed", "Cannot release the app-server startup barrier.")
                close_barrier()
            answer = object_value(
                await server.request(
                    "initialize",
                    {"clientInfo": {"name": "arbol-codex-driver", "version": identity["version"]}},
                    cancellation=cancellation,
                )
            )
            codex_home = string(answer.get("codexHome"))
            try:
                correct_home = (
                    codex_home is not None
                    and Path(codex_home).is_absolute()
                    and Path(codex_home).resolve(strict=True) == home.resolve(strict=True)
                )
            except OSError:
                correct_home = False
            if not correct_home:
                raise Failure("tool_failed", "codex opened a different Subscription home.")
            agent = string(answer.get("userAgent"))
            match = re.match(r"^[^/]+/([^ ]+)", agent or "")
            server.tool_version = match[1] if match is not None else None
            if server.tool_version is None or re.fullmatch(r"\d+\.\d+\.\d+", server.tool_version) is None:
                raise Failure("tool_failed", "codex returned an unrecognised handshake version.")
            if not supported_version(server.tool_version):
                raise Failure("tool_unsupported",
                              f"codex {server.tool_version} is unsupported; needed {OLDEST_SUPPORTED} or newer.",
                              {"detail": {"basis": "fields", "toolVersion": server.tool_version,
                                          "neededVersion": OLDEST_SUPPORTED}, "remedy": "Update codex."})
            await server.send({"method": "initialized"})
            return server
        except BaseException:
            close_barrier()  # EOF prevents vendor exec before bounded cleanup.
            stopped = cancellation.stopped_at if cancellation is not None else None
            await server.end(
                None if stopped is None else stopped + fixed_wait(15000, env),
                None if stopped is None else stopped + fixed_wait(2000, env),
            )
            raise
        finally:
            close_barrier()

    async def send(self, value: Json) -> None:
        if self.failure is not None:
            raise self.failure
        assert self.child.stdin is not None
        try:
            owner_config = (
                isinstance(value, dict)
                and value.get("method") in ("thread/start", "thread/resume")
                and "mcp_servers" in object_value(object_value(value.get("params")).get("config"))
            )
            # TOML has exact 64-bit integers. This private vendor payload must
            # not use the contract serializer's ECMAScript number rounding.
            encoded = json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":")) if owner_config else dumps(value)
            self.child.stdin.write((encoded + "\n").encode())
            await self.child.stdin.drain()
        except (OSError, ConnectionError):
            self.fail(Failure("tool_failed", "Cannot send a request to codex."))
            assert self.failure is not None
            raise self.failure from None

    async def request(
        self, method: str, params: Json, *, cancellation: Cancellation | None = None, timeout: float | None = None
    ) -> Json:
        if cancellation is not None:
            cancellation.check()
        if self.failure is not None:
            raise self.failure
        id_ = self.next_id
        self.next_id += 1
        future: asyncio.Future[Json] = asyncio.get_running_loop().create_future()
        self.pending[id_] = future
        self.notification_space.set()

        async def exchange() -> Json:
            await self.send({"id": id_, "method": method, "params": params})
            return await future

        try:
            return await interruptible(exchange(), cancellation, self.timeout if timeout is None else timeout)
        except TimeoutError:
            error = Failure("tool_failed", f"codex did not answer {method} within the request timeout.")
            self.fail(error)
            self.schedule_end()
            raise error from None
        finally:
            self.pending.pop(id_, None)
            if not future.done():
                future.cancel()
            elif not future.cancelled():
                future.exception()

    def take_notifications(self) -> list[Notification]:
        result, self.notifications = self.notifications, []
        self.notification_bytes = 0
        self.notification_space.set()
        return result

    async def next_notification(
        self, *, cancellation: Cancellation | None = None, timeout: float | None = None
    ) -> Notification:
        if cancellation is not None:
            cancellation.check()
        if self.notifications:
            notice = self.notifications.pop(0)
            self.notification_bytes -= notice.size
            self.notification_space.set()
            return notice
        if self.failure is not None:
            raise self.failure
        if self.notification_waiter is not None:
            raise Failure("internal", "An app-server notification reader is already waiting.")
        future: asyncio.Future[Notification] = asyncio.get_running_loop().create_future()
        self.notification_waiter = future
        try:
            return await interruptible(future, cancellation, timeout)
        except TimeoutError:
            raise Failure("tool_failed", "Timed out waiting for codex output.") from None
        finally:
            if self.notification_waiter is future:
                self.notification_waiter = None

    async def wait_for_notification(
        self,
        method: str,
        predicate: Callable[[Json], bool] = lambda _: True,
        *,
        cancellation: Cancellation | None = None,
        timeout: float | None = None,
    ) -> Json:
        if cancellation is not None:
            cancellation.check()
        for index, notice in enumerate(self.notifications):
            if notice.method == method and predicate(notice.params):
                self.notifications.pop(index)
                self.notification_bytes -= notice.size
                self.notification_space.set()
                return notice.params
        if self.failure is not None:
            raise self.failure
        future: asyncio.Future[Json] = asyncio.get_running_loop().create_future()
        watcher = (method, predicate, future)
        self.watchers.append(watcher)
        try:
            return await interruptible(future, cancellation, self.timeout if timeout is None else timeout)
        except TimeoutError:
            raise Failure("tool_failed", f"Timed out waiting for codex {method}.") from None
        finally:
            if watcher in self.watchers:
                self.watchers.remove(watcher)

    def fail(self, error: Failure) -> None:
        self.notification_space.set()
        if self.failure is None:
            self.failure = error
        for future in [*self.pending.values(), *(watcher[2] for watcher in self.watchers)]:
            if not future.done():
                future.set_exception(self.failure)
        self.pending.clear()
        self.watchers.clear()
        if self.notification_waiter is not None and not self.notification_waiter.done():
            self.notification_waiter.set_exception(self.failure)
            self.notification_waiter = None

    def schedule_end(self) -> None:
        task = asyncio.create_task(self.end())
        self.background.add(task)

        def done(completed: asyncio.Task[None]) -> None:
            self.background.discard(completed)
            if not completed.cancelled():
                completed.exception()

        task.add_done_callback(done)

    def notify(self, method: str, params: Json) -> None:
        self.last_notification_at = time.monotonic()
        if self.on_notification is not None:
            self.on_notification(method, params)
        waiter = self.notification_waiter
        if waiter is not None and not waiter.done():
            self.notification_waiter = None
            waiter.set_result(Notification(method, params))
            return
        for watcher in self.watchers[:]:
            try:
                matches = watcher[0] == method and watcher[1](params)
            except Exception as error:
                self.watchers.remove(watcher)
                if not watcher[2].done():
                    watcher[2].set_exception(error)
                continue
            if matches:
                self.watchers.remove(watcher)
                if not watcher[2].done():
                    watcher[2].set_result(params)
                return
        size = len((dumps({"method": method, "params": params}) + "\n").encode())
        self.notification_bytes += size
        self.notifications.append(Notification(method, params, size))
        # An RPC answer can follow early notices. Keep reading toward that
        # answer, but refuse an unbounded startup burst. With no RPC pending,
        # stdout pauses until the run consumes notices and drains caller output.
        if self.notification_bytes > 32 * 1024 * 1024 or len(self.notifications) > 8192:
            raise OverflowError

    async def notification_capacity(self) -> None:
        while (
            self.failure is None
            and not self.pending
            and (self.notification_bytes >= 16 * 1024 * 1024 or len(self.notifications) >= 4096)
        ):
            self.notification_space.clear()
            await self.notification_space.wait()

    async def consume(self, text: str) -> None:
        message = loads(text)
        if not isinstance(message, dict):
            raise ValueError
        method = string(message.get("method"))
        if method is not None:
            if "id" in message:
                result = (
                    self.on_server_request(method, message.get("params"))
                    if self.on_server_request is not None
                    else None
                )
                response: Object = {
                    "id": message["id"],
                    **(
                        {"error": {"code": -32601, "message": "Method not supported by the Driver."}}
                        if result is None
                        else {"result": result}
                    ),
                }

                async def reply() -> None:
                    try:
                        await interruptible(self.send(response), timeout=self.timeout)
                    except Exception:
                        self.fail(Failure("tool_failed", "Cannot answer a codex server request."))
                        self.schedule_end()

                task = asyncio.create_task(reply())
                self.background.add(task)
                task.add_done_callback(self.background.discard)
            else:
                self.notify(method, message.get("params"))
        elif type(message.get("id")) in (int, float) and ("result" in message) != ("error" in message):
            future = self.pending.pop(cast(int, message["id"]), None)
            if future is not None and not future.done():
                if "error" in message:
                    error = message["error"]
                    future.set_exception(
                        rpc_failure(error, self.private_values)
                        if isinstance(error, dict) and isinstance(error.get("message"), str)
                        else Failure("tool_failed", "codex returned a malformed error.")
                    )
                else:
                    future.set_result(message["result"])
        else:
            raise ValueError

    async def read_stdout(self) -> None:
        assert self.child.stdout is not None
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        buffer = ""
        try:
            while chunk := await self.child.stdout.read(65536):
                if self.failure is not None:
                    continue
                buffer += decoder.decode(chunk)
                while "\n" in buffer:
                    await self.notification_capacity()
                    line, buffer = buffer.split("\n", 1)
                    if len(line.encode()) > 4 * 1024 * 1024:
                        raise OverflowError
                    if line.strip():
                        await self.consume(line)
                if len(buffer.encode()) > 4 * 1024 * 1024:
                    raise OverflowError
            buffer += decoder.decode(b"", final=True)
            self.fail(
                Failure(
                    "tool_failed",
                    "codex returned an incomplete app-server message."
                    if buffer.strip()
                    else "The codex app-server output ended.",
                    {"detail": {"basis": "fields", "excerpt": self.log_tail}},
                )
            )
        except (ValueError, OverflowError) as error:
            self.fail(
                Failure(
                    "tool_failed",
                    "codex returned an oversized app-server message."
                    if isinstance(error, OverflowError)
                    else "codex returned a malformed app-server message.",
                )
            )
            self.schedule_end()
        except (OSError, ConnectionError):
            self.fail(Failure("tool_failed", "The codex app-server output ended."))
            self.schedule_end()
        except Exception:
            self.fail(Failure("tool_failed", "Cannot process a codex app-server message."))
            self.schedule_end()

    async def read_stderr(self) -> None:
        assert self.child.stderr is not None
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        scrubber = DiagnosticScrubber(self.private_values)
        while chunk := await self.child.stderr.read(65536):
            self.log_tail = safe_text(self.log_tail + scrubber.feed(decoder.decode(chunk)), limit=64 * 1024)
        self.log_tail = safe_text(
            self.log_tail + scrubber.feed(decoder.decode(b"", final=True), final=True), limit=64 * 1024
        )

    async def monitor(self) -> None:
        while self.child.returncode is None:
            await asyncio.sleep(0.005)
        self.fail(
            Failure(
                "tool_failed",
                "The codex app-server exited.",
                {"detail": {"basis": "fields", "toolExit": self.child.returncode, "excerpt": self.log_tail}},
            )
        )
        try:
            await force_process_groups(list(self.groups.values()), time.monotonic() + 1)
        except Exception:
            self.schedule_end()

    async def capture_process_groups(self) -> list[Owner]:
        for owner in await collect_process_groups(self.owner):
            self.groups[owner["pid"]] = owner
        return list(self.groups.values())

    def eof(self) -> None:
        if self.child.stdin is not None and not self.child.stdin.is_closing():
            self.child.stdin.close()

    async def close(self, deadline: float | None = None, force_at: float | None = None) -> None:
        if self.closing is None:
            self.closing = asyncio.create_task(self._close(deadline, force_at))
        await asyncio.shield(self.closing)

    async def _close(self, deadline: float | None, force_at: float | None) -> None:
        self.fail(Failure("tool_failed", "The codex app-server was stopped."))
        deadline = time.monotonic() + fixed_wait(10000) if deadline is None else deadline
        error: BaseException | None = None
        remaining: list[Owner] = []
        try:
            try:
                await self.capture_process_groups()
            except Exception as failure:
                error = failure
            self.eof()
            remaining = await end_process_groups(list(self.groups.values()), deadline, force_at)
        except Exception as failure:
            error = error or failure
        finally:
            if error is not None:
                try:
                    await force_process_groups(list(self.groups.values()), deadline)
                except Exception:
                    pass
            cast(ChildTransport, self.child)._transport.close()
            try:
                await asyncio.wait_for(self.child.wait(), self.cleanup_grace)
            except TimeoutError:
                pass
            for task in self.tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*self.tasks, return_exceptions=True)
        if error is not None:
            raise error
        if remaining:
            raise Failure(
                "tool_failed",
                "Some codex processes could not be ended.",
                {"detail": {"basis": "fields", "excerpt": dumps([owner_json(owner) for owner in remaining])}},
            )

    async def end(self, deadline: float | None = None, force_at: float | None = None) -> None:
        if self.closing is not None:
            await self.close(deadline, force_at)
            return
        if self.ending is None:
            self.ending = asyncio.create_task(self._end(deadline, force_at))
        await asyncio.shield(self.ending)

    async def _end(self, deadline: float | None, force_at: float | None) -> None:
        deadline = deadline if deadline is not None else time.monotonic() + fixed_wait(15000)
        error: Exception | None = None
        try:
            await self.capture_process_groups()
        except Exception as failure:
            error = failure
        finally:
            self.eof()
            eof_deadline = min(deadline, force_at if force_at is not None else time.monotonic() + fixed_wait(2000))
            while self.child.returncode is None and time.monotonic() < eof_deadline and self.closing is None:
                await asyncio.sleep(min(0.01, max(0.001, eof_deadline - time.monotonic())))
            await self.close(deadline, force_at)
        if error is not None:
            raise error
