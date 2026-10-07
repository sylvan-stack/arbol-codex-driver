import asyncio
import codecs
import json
import math
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

from .build import build_identity
from .cancellation import Cancellation, interruptible
from .environment import clean_environment
from .errors import Failure, safe_text
from .json_types import Json, Object, dumps, loads, object_value, string
from .owner_setup import DiagnosticScrubber, sanitize_diagnostic
from .process_groups import collect_process_groups, end_process_groups, force_process_groups
from .state import Owner, atomic_write, fixed_wait, owner_json, private_directory, process_owner

DRIVER_CONFIG = 'check_for_update_on_startup = false\nweb_search = "live"\ncli_auth_credentials_store = "file"\n\n[analytics]\nenabled = false\n\n[features]\nmemories = false\n'


def write_driver_config(home: Path) -> None:
    private_directory(home)
    atomic_write(home / "config.toml", DRIVER_CONFIG)


def validate_driver_config(value: Json) -> Object:
    config = object_value(object_value(value).get("config"))
    if (
        config.get("check_for_update_on_startup") is not False
        or config.get("web_search") != "live"
        or config.get("cli_auth_credentials_store") != "file"
        or object_value(config.get("analytics")).get("enabled") is not False
        or object_value(config.get("features")).get("memories") is not False
    ):
        raise Failure("tool_failed", "codex did not apply the Driver configuration.")
    return config


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
                {"detail": detail, **({"remedy": "Sign in again."} if structured or wording else {})}, private_values
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
    ) -> None:
        self.child, self.owner, self.timeout, self.cleanup_grace = child, owner, timeout, cleanup_grace
        self.on_server_request = on_server_request
        self.private_values = private_values
        self.next_id = 1
        self.pending: dict[int, asyncio.Future[Json]] = {}
        self.notifications: list[Notification] = []
        self.notification_bytes = 0
        self.notification_space = asyncio.Event()
        self.watchers: list[tuple[str, Callable[[Json], bool], asyncio.Future[Json]]] = []
        self.notification_waiter: asyncio.Future[Notification] | None = None
        self.failure: Failure | None = None
        self.effective_config: Object = {}
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
        home: Path,
        env: dict[str, str],
        cwd: Path | None = None,
        cancellation: Cancellation | None = None,
        request_timeout: float = 30,
        on_spawn: Callable[[Owner], Awaitable[None]] | None = None,
        on_server_request: Callable[[str, Json], Json] | None = None,
        launch_identity_path: Path | None = None,
        private_values: tuple[str, ...] = (),
    ) -> AppServer:
        if cancellation is not None:
            cancellation.check()
        if not math.isfinite(request_timeout) or request_timeout <= 0:
            raise Failure("invalid_input", "The app-server request timeout must be a positive finite number.")
        home = home.absolute()
        write_driver_config(home)
        identity = build_identity()
        arguments = [tool_path, "app-server"]
        if launch_identity_path is not None:
            arguments = [
                "/bin/sh",
                "-c",
                'umask 077; ledger="$1.write"; { printf "%s\\n" "$$"; TZ=UTC LC_ALL=C /bin/ps -p "$$" -o lstart=; } > "$ledger" && /bin/mv -f "$ledger" "$1" || exit 1; exec "$2" app-server',
                "arbol-codex-launch",
                str(launch_identity_path),
                tool_path,
            ]
        try:
            child = await asyncio.create_subprocess_exec(
                *arguments,
                cwd=cwd or home,
                env=clean_environment(env, env.get("HOME") or str(Path.home()), str(home)),
                start_new_session=True,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError:
            raise Failure("tool_failed", "Cannot start the codex app-server.") from None
        from .json_types import now

        server = cls(
            child,
            {"pid": child.pid, "startedAt": now()},
            request_timeout,
            fixed_wait(500, env),
            on_server_request,
            private_values,
        )
        try:
            owner = await process_owner(child.pid)
            if owner is None:
                raise Failure("tool_failed", "Cannot identify the codex app-server process.")
            server.owner = owner
            server.groups[owner["pid"]] = owner
            if on_spawn is not None:
                await on_spawn(owner)
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
            await server.send({"method": "initialized"})
            server.effective_config = validate_driver_config(
                await server.request("config/read", {}, cancellation=cancellation)
            )
            return server
        except BaseException:
            stopped = cancellation.stopped_at if cancellation is not None else None
            await server.end(
                None if stopped is None else stopped + fixed_wait(15000, env),
                None if stopped is None else stopped + fixed_wait(2000, env),
            )
            raise

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
