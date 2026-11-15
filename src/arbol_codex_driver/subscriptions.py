import asyncio
import builtins
import os
import shutil
import signal
import time
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from urllib.parse import urlsplit

from .app_server import AppServer
from .cancellation import Cancellation
from .catalog import builtin_catalog, normalize_account, normalize_usage, read_model_catalog
from .errors import Failure, safe_failure
from .identity import (
    IdentityJournal,
    LifetimeSnapshot,
    PendingIdentity,
    canonical_id,
    expected_proof,
    lifetime_matches,
)
from .identity_protocol import PrivateDirectory
from .json_types import Json, Object, iso, now, object_value, string, timestamp
from .run_limits import merge_usage_reports
from .runs import Runs
from .state import (
    Owner,
    State,
    fixed_wait,
    owner_alive,
    owner_json,
    parse_owner,
    private_directory,
    process_owner,
    read_json,
    write_json,
)
from .tool import inspect_tool, require_tool

FAMILIES: list[Json] = [
    {
        "id": "chatgpt",
        "label": "ChatGPT",
        "auth": "vendor_login",
        "settings": {"type": "object", "properties": {}, "additionalProperties": False},
    }
]


def parse_record(value: Json, id_: str) -> Object:
    def bad() -> None:
        raise Failure("internal", f"Malformed Subscription record for {id_}.")

    keys = {
        "id",
        "family",
        "label",
        "auth",
        "state",
        "account",
        "problem",
        "lastUsage",
        "createdAt",
        "updatedAt",
        "checkedAt",
    }
    if (
        not isinstance(value, dict)
        or value.get("id") != id_
        or value.get("family") != "chatgpt"
        or value.get("auth") != "vendor_login"
        or not isinstance(value.get("label"), str)
        or not value["label"]
        or value.get("state") not in ("signed_out", "signed_in", "needs_attention")
        or any(timestamp(value.get(key)) is None for key in ("createdAt", "updatedAt"))
    ):
        bad()
    assert isinstance(value, dict)
    if set(value) - keys or (value["state"] == "needs_attention") != ("problem" in value):
        bad()
    problem = value.get("problem")
    if "problem" in value and (
        not isinstance(problem, dict)
        or problem.get("code") != "credential_rejected"
        or not isinstance(problem.get("message"), str)
        or not isinstance(problem.get("retryable"), bool)
    ):
        bad()
    if "checkedAt" in value and timestamp(value["checkedAt"]) is None:
        bad()
    account = value.get("account")
    if "account" in value and (
        not isinstance(account, dict)
        or any(
            key not in ("name", "email", "organization", "plan") or not isinstance(item, str)
            for key, item in object_value(account).items()
        )
    ):
        bad()
    usage = value.get("lastUsage")
    if "lastUsage" in value and (
        not isinstance(usage, dict)
        or usage.get("outcome") != "ok"
        or timestamp(usage.get("fetchedAt")) is None
        or not isinstance(usage.get("windows"), list)
    ):
        bad()
    return value


def parse_progress(value: Json) -> Object:
    if (
        not isinstance(value, dict)
        or timestamp(value.get("expiresAt")) is None
        or "operation" in value
        and value["operation"] not in ("sign_in", "sign_out", "remove")
    ):
        raise Failure("internal", "Malformed sign-in record.")
    owner = parse_owner(value.get("owner"))
    if "tool" in value:
        parse_owner(value["tool"])
    if "lifetime" in value:
        LifetimeSnapshot.parse(value["lifetime"])
    return {
        **value,
        "owner": owner_json(owner),
        "attempt": value.get("attempt")
        if isinstance(value.get("attempt"), str)
        else f"{owner['pid']}:{owner['startedAt']}",
        "operation": value.get("operation", "sign_in"),
    }


class Subscriptions:
    def __init__(
        self,
        state: State,
        settings: Object,
        notices: list[Object],
        settings_file: Path,
        env: dict[str, str],
        cancellation: Cancellation | None = None,
    ) -> None:
        self.state, self.settings, self.notices, self.settings_file, self.env, self.cancellation = (
            state,
            settings,
            notices,
            settings_file,
            env,
            cancellation,
        )

    def file(self, id_: str, name: str) -> Path:
        return self.state.subscription(id_) / name

    def app_server_home(self, id_: str) -> Path | None:
        """None selects native Codex; historical isolated homes stay in place."""
        return None if id_ == "chatgpt" else self.file(id_, "home")

    def record(self, id_: str) -> Object:
        value = read_json(self.file(id_, "record.json"))
        if value is not None:
            return parse_record(value, id_)
        if id_ != "chatgpt":
            raise Failure("not_found", "Subscription was not found.")
        stat = (self.state.directory / "format").stat()
        created = iso(getattr(stat, "st_birthtime", stat.st_ctime))
        return {
            "id": id_,
            "family": "chatgpt",
            "label": "ChatGPT",
            "auth": "vendor_login",
            "state": "signed_out",
            "createdAt": created,
            "updatedAt": created,
        }

    async def identity(self, id_: str, expect: str | None = None) -> Object:
        id_, expected = canonical_id(id_), expected_proof(expect)
        self.state.assert_admitted().require_proof()

        async def capture() -> Object:
            # Validate only the local catalogue record (including implicit
            # chatgpt). get/reap/settings/auth/vendor discovery is excluded.
            self.state.assert_admitted().require_proof()
            self.record(id_)
            return self.state.assert_admitted().capture_proof(id_, expected)

        return await self.state.with_subscription_lock(id_, capture, self.env)

    def progress(self, id_: str) -> Object | None:
        value = read_json(self.file(id_, "sign-in.json"))
        return None if value is None else parse_progress(value)

    def progress_matches(self, id_: str, progress: Object) -> bool:
        # Missing legacy evidence is never promoted to the current proof.
        lifetime = LifetimeSnapshot.parse(progress["lifetime"]) if "lifetime" in progress else None
        return lifetime_matches(self.state.assert_admitted(), id_, lifetime)

    @staticmethod
    def same_progress(current: Object, captured: Object) -> bool:
        return (
            current["attempt"] == captured["attempt"]
            and parse_owner(current.get("owner")) == parse_owner(captured.get("owner"))
            and current.get("lifetime") == captured.get("lifetime")
        )

    async def get(self, id_: str) -> Object:
        record = self.record(id_)
        await self.reap(id_)
        family_settings = object_value(
            object_value(object_value(self.settings.get("subscriptions")).get(id_)).get("settings")
        )
        for key in family_settings:
            # The family chatgpt has no settings, so every key there is unknown (DRV-D34).
            raise Failure(
                "invalid_input", f"Settings file {self.settings_file}: unknown field subscriptions.{id_}.settings.{key}."
            )
        result: Object = {**record, "settings": {}}
        pending = self.progress(id_)
        if (
            pending is not None
            and pending["operation"] == "sign_in"
            and await owner_alive(parse_owner(pending.get("owner")))
        ):
            result["state"] = "signing_in"
            result.pop("problem", None)
        return result

    async def observe(self, id_: str, *, signed_in: bool = False) -> tuple[Object, LifetimeSnapshot | None]:
        # Retain normal local settings/reap behavior before the atomic capture.
        initial = await self.get(id_)
        await self.settle_identity(id_)

        async def capture() -> tuple[Object, LifetimeSnapshot | None]:
            current = self.record(id_)
            result: Object = {**current, "settings": {}}
            if initial["state"] == "signing_in" and self.progress(id_) is not None:
                result["state"] = "signing_in"
                result.pop("problem", None)
            if signed_in and result["state"] != "signed_in":
                raise Failure("not_signed_in", "Sign in to this Subscription first.", {"remedy": "Sign in again."})
            return result, LifetimeSnapshot.capture(self.state.assert_admitted(), id_)

        return await self.state.with_subscription_lock(id_, capture, self.env)

    def ids(self) -> list[str]:
        ids = ["chatgpt"]
        directory = self.state.directory / "subscriptions"
        if directory.exists():
            ids.extend(
                entry.name
                for entry in directory.iterdir()
                if entry.is_dir()
                and entry.name not in ids
                and read_json(self.file(entry.name, "record.json")) is not None
            )
        return ids

    async def list(self) -> list[Json]:
        return [await self.get(id_) for id_ in self.ids()]

    async def create(
        self,
        family: str | bool | builtins.list[str] | None,
        label: str | bool | builtins.list[str] | None,
        explicit_id: str | None = None,
    ) -> Object:
        if family != "chatgpt":
            raise Failure("invalid_input", "Choose the Subscription family chatgpt.")
        raise Failure("invalid_input", "ChatGPT uses the single native chatgpt Subscription; a second cannot be created.")

    async def reap(self, id_: str) -> None:
        pending = self.progress(id_)
        if pending is None or await owner_alive(parse_owner(pending.get("owner"))):
            return
        if "tool" in pending:
            tool = parse_owner(pending["tool"])
            if await owner_alive(tool):
                try:
                    os.killpg(tool["pid"], signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass

        async def change() -> None:
            current = self.progress(id_)
            if (
                current is not None
                and self.same_progress(current, pending)
                and self.progress_matches(id_, pending)
                and not await owner_alive(parse_owner(current.get("owner")))
            ):
                self.file(id_, "sign-in.json").unlink(missing_ok=True)

        await self.state.with_subscription_lock(id_, change, self.env)

    async def update(self, id_: str, label: str | None) -> Object:
        await self.get(id_)
        await self.reap(id_)
        self.state.clear_unfinished_writes()
        if label is None:
            return await self.get(id_)
        if not label:
            raise Failure("invalid_input", "Give the Subscription a non-empty label.")

        async def change() -> None:
            current = self.record(id_)
            # Relabeling preserves an existing witness, but cannot cross an
            # unsettled removal or manufacture a replacement lifetime.
            state = self.state.assert_admitted()
            if state.format == 2 and IdentityJournal(state, id_).pending() is not None:
                raise Failure("in_use", "Subscription identity settlement is pending.")
            if id_ != "chatgpt":
                private_directory(self.file(id_, "home"))
            write_json(self.file(id_, "record.json"), {**current, "label": label, "updatedAt": now()})

        await self.state.with_subscription_lock(id_, change, self.env)
        return await self.get(id_)

    async def require_signed_in(self, id_: str) -> Object:
        item = await self.get(id_)
        if item["state"] != "signed_in":
            raise Failure("not_signed_in", "Sign in to this Subscription first.", {"remedy": "Sign in again."})
        return item

    async def run_report(
        self, initial: Object, error: Object, *, lifetime: LifetimeSnapshot | None = None,
    ) -> None:
        if error["code"] == "credential_rejected":
            await self.merge(initial, {"state": "needs_attention", "problem": error, "checkedAt": now()}, lifetime=lifetime)

    async def store_run_usage(
        self, initial: Object, usage: Object, *, lifetime: LifetimeSnapshot | None = None,
    ) -> None:
        """Save a run snapshot without restoring a replaced or signed-out login."""
        id_ = str(initial["id"])

        async def change() -> None:
            if not lifetime_matches(self.state.assert_admitted(), id_, lifetime):
                return
            try:
                current = self.record(id_)
            except Failure as error:
                if error.result["code"] == "not_found":
                    return
                raise
            if (
                current["state"] == "signed_out"
                or any(current.get(key) != initial.get(key) for key in ("state", "checkedAt", "createdAt", "account"))
                or self.progress(id_) is not None
            ):
                return
            previous = object_value(current.get("lastUsage"))
            observed = timestamp(usage.get("fetchedAt"))
            stored = timestamp(previous.get("fetchedAt"))
            if observed is None or stored is not None and stored > observed:
                return
            report = merge_usage_reports(previous, usage, object_value(initial.get("lastUsage")))
            write_json(self.file(id_, "record.json"), {**current, "lastUsage": report, "updatedAt": now()})

        await self.state.with_subscription_lock(id_, change, self.env)

    async def start(
        self,
        id_: str,
        on_spawn: Callable[[Owner], Awaitable[None]] | None = None,
        cancellation: Cancellation | None = None,
    ) -> AppServer:
        cancellation = cancellation or self.cancellation
        tool = await inspect_tool(self.state, string(self.settings.get("toolPath")), self.env, cancellation)
        return await AppServer.start(
            tool_path=require_tool(tool),
            home=self.app_server_home(id_),
            env=self.env,
            cancellation=cancellation,
            on_spawn=on_spawn,
        )

    async def merge(
        self, initial: Object, fields: Object, *, lifetime: LifetimeSnapshot | None = None,
    ) -> Object:
        id_ = str(initial["id"])

        async def change() -> None:
            if not lifetime_matches(self.state.assert_admitted(), id_, lifetime):
                return
            try:
                current = self.record(id_)
            except Failure as error:
                if error.result["code"] == "not_found":
                    return
                raise
            if (
                any(current.get(key) != initial.get(key) for key in ("state", "checkedAt", "createdAt"))
                or self.progress(id_) is not None
            ):
                raise Failure("in_use", "The Subscription changed while Codex was answering. Try again.")
            next_ = {**current, **fields, "updatedAt": now()}
            if next_["state"] != "needs_attention":
                next_.pop("problem", None)
            write_json(self.file(id_, "record.json"), next_)

        await self.state.with_subscription_lock(id_, change, self.env)
        return await self.get(id_)

    async def check(self, id_: str) -> Object:
        initial, lifetime = await self.observe(id_)
        if initial["state"] == "signed_out":
            raise Failure("not_signed_in", "Sign in to this Subscription first.", {"remedy": "Sign in again."})
        server: AppServer | None = None
        try:
            server = await self.start(id_)
            account = normalize_account(
                await server.request("account/read", {"refreshToken": True}, cancellation=self.cancellation)
            )
            return await self.merge(
                initial,
                {"state": "signed_in", "account": account, "checkedAt": now()}
                if account is not None
                else {
                    "state": "needs_attention",
                    "problem": Failure(
                        "credential_rejected", "The Codex home has no ChatGPT account.", {"remedy": "Sign in again."}
                    ).result,
                    "checkedAt": now(),
                },
                lifetime=lifetime,
            )
        except Failure as error:
            if error.result["code"] == "credential_rejected":
                return await self.merge(
                    initial, {"state": "needs_attention", "problem": error.result, "checkedAt": now()}, lifetime=lifetime,
                )
            raise
        finally:
            if server is not None:
                await server.close()

    async def usage(self, id_: str) -> Object:
        initial, lifetime = await self.observe(id_)
        if initial["state"] != "signed_in":
            return {
                "outcome": "needs_sign_in",
                "fetchedAt": now(),
                "windows": [],
                "message": "Sign in to this Subscription first.",
            }
        server: AppServer | None = None
        try:
            server = await self.start(id_)
            usage = normalize_usage(
                await server.request("account/rateLimits/read", {}, cancellation=self.cancellation),
                string(object_value(initial.get("account")).get("plan")),
            )
            await self.merge(initial, {"lastUsage": usage}, lifetime=lifetime)
            return usage
        except Exception as error:
            if isinstance(error, Failure) and error.result["code"] == "credential_rejected":
                await self.merge(
                    initial, {"state": "needs_attention", "problem": error.result, "checkedAt": now()}, lifetime=lifetime,
                )
                return {"outcome": "needs_sign_in", "fetchedAt": now(), "windows": [], "message": str(error)}
            if isinstance(error, Failure) and error.result["code"] in ("tool_missing", "tool_unsupported"):
                raise
            return {
                "outcome": "unavailable",
                "fetchedAt": now(),
                "windows": [],
                "message": safe_failure(error)["message"],
            }
        finally:
            if server is not None:
                await server.close()

    async def models(self, id_: str) -> Object:
        initial, lifetime = await self.observe(id_, signed_in=True)
        server: AppServer | None = None
        try:
            server = await self.start(id_)

            async def request(method: str, params: Json) -> Json:
                assert server is not None
                return await server.request(method, params, cancellation=self.cancellation)

            return await read_model_catalog(request)
        except Exception as error:
            if isinstance(error, Failure) and error.result["code"] == "credential_rejected":
                await self.merge(
                    initial, {"state": "needs_attention", "problem": error.result, "checkedAt": now()}, lifetime=lifetime,
                )
                raise
            if isinstance(error, Failure) and error.result["code"] in ("tool_missing", "tool_unsupported"):
                raise
            if self.cancellation is not None:
                self.cancellation.check()
            return builtin_catalog()
        finally:
            if server is not None:
                await server.close()

    async def stop_pending(self, id_: str, pending: Object, reason: str = "replaced") -> None:
        owner = parse_owner(pending.get("owner"))
        if not await owner_alive(owner):
            await self.reap(id_)
            return

        async def change() -> bool:
            current = self.progress(id_)
            if current is None or not self.same_progress(current, pending) or not self.progress_matches(id_, pending):
                return False
            write_json(self.file(id_, "sign-in.json"), {**current, "stopReason": reason})
            return True

        if not await self.state.with_subscription_lock(id_, change, self.env):
            raise Failure("in_use", "The account operation lifetime is no longer available.")
        if await owner_alive(owner):
            try:
                os.kill(owner["pid"], signal.SIGTERM)
            except ProcessLookupError:
                pass
        deadline = time.monotonic() + fixed_wait(5000, self.env)
        while (current := self.progress(id_)) is not None and current["attempt"] == pending["attempt"]:
            if not await owner_alive(owner):
                await self.reap(id_)
                return
            if time.monotonic() > deadline:
                raise Failure("in_use", "The previous account operation did not stop.")
            await asyncio.sleep(fixed_wait(25, self.env))

    async def reserve(self, id_: str, operation: str, by_code: bool = False) -> Object:
        await self.get(id_)
        await self.settle_identity(id_)
        self.state.clear_unfinished_writes()
        owner = await process_owner(os.getpid())
        if owner is None:
            raise Failure("internal", "Cannot identify the Driver process.")
        progress: Object = {
            "owner": owner_json(owner),
            "attempt": str(uuid.uuid4()),
            "operation": operation,
            "byCode": by_code,
            "expiresAt": iso(time.time() + fixed_wait(300000, self.env)),
        }
        while True:
            if self.cancellation is not None:
                self.cancellation.check()
            await self.reap(id_)

            async def change() -> Object | None:
                record = self.record(id_)
                current = self.progress(id_)
                if current is not None:
                    if not self.progress_matches(id_, current):
                        raise Failure("in_use", "The prior account operation lifetime is unavailable; recover it offline.")
                    return current
                lifetime = LifetimeSnapshot.capture(self.state.assert_admitted(), id_)
                if lifetime is not None:
                    progress["lifetime"] = lifetime.document()
                if operation == "sign_in":
                    cleared: Object = {**record, "state": "signed_out", "updatedAt": now(), "checkedAt": now()}
                    for key in ("account", "problem", "lastUsage"):
                        cleared.pop(key, None)
                    write_json(self.file(id_, "record.json"), cleared)
                write_json(self.file(id_, "sign-in.json"), progress)
                return None

            previous = await self.state.with_subscription_lock(id_, change, self.env)
            if previous is None:
                return progress
            if previous["operation"] == "sign_in":
                await self.stop_pending(id_, previous, "replaced" if operation == "sign_in" else "signed_out")
            else:
                deadline = time.monotonic() + fixed_wait(10000, self.env)
                while (
                    (current := self.progress(id_)) is not None
                    and current["attempt"] == previous["attempt"]
                    and await owner_alive(parse_owner(previous.get("owner")))
                ):
                    if self.cancellation is not None:
                        self.cancellation.check()
                    if time.monotonic() > deadline:
                        raise Failure("in_use", "An account operation is still in progress.")
                    await asyncio.sleep(fixed_wait(50, self.env))

    async def finish(self, id_: str, progress: Object, fields: Object | None = None) -> None:
        async def change() -> None:
            pending = self.progress(id_)
            if (
                pending is None or not self.same_progress(pending, progress)
                or not self.progress_matches(id_, progress)
            ):
                if fields is not None and fields.get("state") == "signed_in":
                    raise Failure("in_use", "Another sign-in took its place.")
                return
            if fields is not None and fields.get("state") == "signed_in" and pending.get("stopReason"):
                raise Failure("in_use", "Another sign-in took its place.")
            if fields is not None:
                next_ = {**self.record(id_), **fields, "updatedAt": now()}
                if next_["state"] == "signed_out":
                    for key in ("account", "problem", "lastUsage"):
                        next_.pop(key, None)
                elif next_["state"] == "signed_in":
                    next_.pop("problem", None)
                write_json(self.file(id_, "record.json"), next_)
            self.file(id_, "sign-in.json").unlink(missing_ok=True)

        await self.state.with_subscription_lock(id_, change, self.env)

    async def set_tool(self, id_: str, progress: Object, tool: Owner) -> None:
        async def change() -> None:
            current = self.progress(id_)
            if (
                current is None or not self.same_progress(current, progress)
                or not self.progress_matches(id_, progress)
            ):
                raise Failure("in_use", "Another account operation took its place.")
            write_json(self.file(id_, "sign-in.json"), {**current, "tool": owner_json(tool)})

        await self.state.with_subscription_lock(id_, change, self.env)

    async def local_login(self, id_: str, own: Object) -> None:
        def rank(progress: Object) -> str:
            owner = parse_owner(progress.get("owner"))
            return f"{owner['startedAt']}:{owner['pid']:012}:{progress['attempt']}"

        for other_id in self.ids():
            if other_id == id_:
                continue
            pending = self.progress(other_id)
            if (
                pending is None
                or pending["operation"] != "sign_in"
                or pending.get("byCode")
                or not await owner_alive(parse_owner(pending.get("owner")))
            ):
                continue
            if rank(pending) < rank(own):
                await self.stop_pending(other_id, pending)
            else:
                raise Failure("in_use", "Another local ChatGPT sign-in took its place.")

    async def sign_in(self, id_: str, by_code: bool, emit: Callable[[Json], Awaitable[None]]) -> int:
        progress: Object | None = None
        server: AppServer | None = None
        login_id: str | None = None
        success = False
        cancellation = Cancellation()
        timer: asyncio.TimerHandle | None = None
        relay: asyncio.Task[None] | None = None

        async def forward_stop() -> None:
            assert self.cancellation is not None
            await self.cancellation.event.wait()
            cancellation.abort()

        try:
            progress = await self.reserve(id_, "sign_in", by_code)
            expiration = timestamp(progress["expiresAt"])
            assert expiration is not None
            timer = asyncio.get_running_loop().call_later(max(0.001, expiration - time.time()), cancellation.abort)
            if self.cancellation is not None:
                relay = asyncio.create_task(forward_stop())
            own = progress

            async def spawned(tool: Owner) -> None:
                await self.set_tool(id_, own, tool)

            server = await self.start(id_, spawned, cancellation)
            account = None
            if id_ == "chatgpt":
                account = normalize_account(
                    await server.request("account/read", {"refreshToken": False}, cancellation=cancellation)
                )
            if account is None:
                if not by_code:
                    await self.local_login(id_, progress)
                result = object_value(
                    await server.request(
                        "account/login/start",
                        {"type": "chatgptDeviceCode" if by_code else "chatgpt"},
                        cancellation=cancellation,
                    )
                )
                login_id = string(result.get("loginId"))
                if login_id is None:
                    raise Failure("tool_failed", "Codex returned an unreadable sign-in answer.")
                address = string(result.get("verificationUrl" if by_code else "authUrl"))
                if address is None or by_code and not isinstance(result.get("userCode"), str):
                    raise Failure("tool_failed", "Codex returned no sign-in address.")
                try:
                    url = urlsplit(address)
                except ValueError:
                    raise Failure("tool_failed", "Codex returned an invalid sign-in address.") from None
                if url.scheme != "https" or url.hostname != "auth.openai.com" or url.username or url.password:
                    raise Failure("tool_failed", "Codex returned an unexpected sign-in host.")
                await emit(
                    {
                        "step": "open_url",
                        "url": address,
                        "allowedHosts": ["auth.openai.com", "127.0.0.1"],
                        "expiresAt": progress["expiresAt"],
                        **({"userCode": result["userCode"]} if by_code else {}),
                    }
                )
                completed = object_value(
                    await server.wait_for_notification(
                        "account/login/completed",
                        lambda value: object_value(value).get("loginId") == login_id,
                        cancellation=cancellation,
                        timeout=max(0.001, expiration - time.time()),
                    )
                )
                if completed.get("success") is not True:
                    raise Failure("vendor_error", string(completed.get("error")) or "Codex sign-in failed.")
                account = normalize_account(
                    await server.request("account/read", {"refreshToken": False}, cancellation=cancellation)
                )
            cancellation.check()
            if account is None:
                raise Failure(
                    "credential_rejected",
                    "Codex did not confirm a ChatGPT account after sign-in.",
                    {"remedy": "Sign in again."},
                )
            pending = self.progress(id_)
            if pending is not None and pending.get("stopReason"):
                raise Failure("in_use", "Another sign-in took its place.")
            await self.finish(id_, progress, {"state": "signed_in", "account": account, "checkedAt": now()})
            success = True
            await emit({"step": "done", "subscription": await self.get(id_)})
            return 0
        except Exception as error:
            pending = self.progress(id_) if progress is not None else None
            failure = safe_failure(error)
            if (
                pending is not None
                and progress is not None
                and pending["attempt"] == progress["attempt"]
                and pending.get("stopReason")
            ):
                failure = Failure("in_use", "Another sign-in took its place.").result
            elif progress is not None and time.time() >= (timestamp(progress["expiresAt"]) or 0):
                failure = Failure("limit_reached", "The sign-in ended after five minutes.").result
            elif self.cancellation is not None and self.cancellation.aborted:
                failure = Failure("vendor_error", "The caller cancelled sign-in.").result
            await emit({"step": "failed", "error": failure})
            return (
                2 if self.cancellation is not None and self.cancellation.aborted and failure["code"] != "in_use" else 1
            )
        finally:
            if timer is not None:
                timer.cancel()
            if relay is not None:
                relay.cancel()
                await asyncio.gather(relay, return_exceptions=True)
            if server is not None:
                if not success:
                    cleanup: list[tuple[str, Object]] = []
                    if login_id is not None:
                        cleanup.append(("account/login/cancel", {"loginId": login_id}))
                    if id_ != "chatgpt":
                        cleanup.append(("account/logout", {}))
                    for method, params in cleanup:
                        try:
                            await server.request(method, params, timeout=fixed_wait(1000, self.env))
                        except Exception:
                            pass
                await server.close()
            if progress is not None:
                await self.finish(id_, progress, None if success else {"state": "signed_out", "checkedAt": now()})

    async def active_runs(self, id_: str, force: bool) -> None:
        runs = Runs(self.state, self.env)
        active = [record for record in await runs.list() if record["subscriptionId"] == id_]
        if active and not force:
            raise Failure("in_use", "A run uses this Subscription. Stop it first or use --force.")
        for record in active:
            await runs.stop(str(record["runId"]))

    async def sign_out(self, id_: str, force: bool = False) -> Object:
        if id_ == "chatgpt":
            raise Failure("invalid_input", "Sign out in codex itself; the native chatgpt Subscription cannot be signed out here.")
        await self.get(id_)
        await self.active_runs(id_, force)
        progress = await self.reserve(id_, "sign_out")
        server: AppServer | None = None
        try:
            await self.active_runs(id_, force)

            async def spawned(tool: Owner) -> None:
                await self.set_tool(id_, progress, tool)

            server = await self.start(id_, spawned)
            await server.request("account/logout", {}, cancellation=self.cancellation)
            await self.finish(id_, progress, {"state": "signed_out", "checkedAt": now()})
            return await self.get(id_)
        finally:
            if server is not None:
                await server.close()
            await self.finish(id_, progress)

    def require_remove_receipt(self, id_: str, progress: Object) -> None:
        current = self.progress(id_)
        expected_owner = parse_owner(progress.get("owner"))
        if (
            current is None or current["attempt"] != progress["attempt"] or current["operation"] != "remove"
            or expected_owner["pid"] != os.getpid() or parse_owner(current.get("owner")) != expected_owner
        ):
            raise Failure("in_use", "The original removal no longer owns this Subscription.")

        state = self.state.assert_admitted()
        if state.format == 2:
            if "lifetime" not in progress or current.get("lifetime") != progress["lifetime"]:
                raise Failure("in_use", "The original removal lifetime is unavailable.")
            lifetime = LifetimeSnapshot.parse(progress["lifetime"])
            if lifetime.subscription != id_ or lifetime.generation != state.generation:
                raise Failure("in_use", "The original removal lifetime is unavailable.")
            journal = IdentityJournal(state, id_)
            pending = journal.pending()
            if pending is None:
                if not lifetime_matches(state, id_, lifetime):
                    raise Failure("in_use", "The original removal lifetime is unavailable.")
            elif pending.operation != "remove" or pending.witness != lifetime.witness:
                raise Failure("in_use", "The original removal lifetime is unavailable.")

    async def settle_identity(self, id_: str) -> bool:
        """Settle a validated local outcome under the short lock, never cleanup."""
        if self.state.assert_admitted().format != 2:
            return False

        async def change() -> bool:
            journal = IdentityJournal(self.state.assert_admitted(), id_)
            pending = journal.pending()
            if pending is None:
                return False
            value = read_json(self.file(id_, "record.json"))
            if value is not None:
                parse_record(value, id_)
            journal.settle(record_present=value is not None)
            return pending.operation == "remove"

        return await self.state.with_subscription_lock(id_, change, self.env)

    def remove_owned_trees(self, id_: str) -> None:
        """No short Subscription lock is held across this filesystem cleanup."""
        parent = self.state.subscription(id_)
        for name in ("home", "chats"):
            path = self.file(id_, name)
            try:
                path.lstat()
            except FileNotFoundError:
                continue
            # Reject links/unsafe roots, including any redirected native home.
            # The operation's progress/journal excludes cooperative replacement.
            with PrivateDirectory(path):
                shutil.rmtree(path)
            try:
                path.lstat()
            except FileNotFoundError:
                pass
            else:
                raise Failure("internal", "Subscription cleanup did not remove its owned directory.")
            with PrivateDirectory(parent) as directory:
                os.fsync(directory.fd)

    async def remove(self, id_: str, force: bool = False) -> None:
        if id_ == "chatgpt":
            raise Failure("invalid_input", "Sign out in codex itself; the native chatgpt Subscription cannot be removed.")
        if await self.settle_identity(id_):
            return  # A validated committed removal, not absence, supplies this outcome.
        await self.get(id_)
        await self.active_runs(id_, force)
        progress = await self.reserve(id_, "remove")
        pending: PendingIdentity | None = None
        potentially_pending = False
        committed = False
        try:
            await self.active_runs(id_, force)
            if self.cancellation is not None:
                self.cancellation.check()

            async def prepare() -> PendingIdentity | None:
                nonlocal potentially_pending
                self.require_remove_receipt(id_, progress)
                self.record(id_)
                state = self.state.assert_admitted()
                if state.format == 1:
                    return None
                proof = state.capture_proof(id_, None)
                # Publication failure may already have renamed the marker; keep
                # original progress rather than guessing that nothing changed.
                potentially_pending = True
                return IdentityJournal(state, id_).begin_remove(str(proof["witness"]))

            pending = await self.state.with_subscription_lock(id_, prepare, self.env)
            if self.cancellation is not None and self.cancellation.aborted:
                if pending is not None:
                    async def cancel() -> None:
                        self.require_remove_receipt(id_, progress)
                        IdentityJournal(self.state.assert_admitted(), id_).cancel_remove(pending)

                    await self.state.with_subscription_lock(id_, cancel, self.env)
                    potentially_pending = False
                self.cancellation.check()
            self.remove_owned_trees(id_)

            async def commit() -> None:
                self.require_remove_receipt(id_, progress)
                value = read_json(self.file(id_, "record.json"))
                if value is not None:
                    parse_record(value, id_)
                state = self.state.assert_admitted()
                # Cleanup succeeded in this original operation. Make receipt
                # deletion durable before claiming the journal committed.
                with PrivateDirectory(self.state.subscription(id_)) as directory:
                    directory.delete("sign-in.json")
                    if state.format == 1:
                        os.unlink("record.json", dir_fd=directory.fd)
                        os.fsync(directory.fd)
                if state.format == 2:
                    if pending is None:
                        raise Failure("internal", "Removal has no captured lifetime settlement.")
                    IdentityJournal(state, id_).complete_remove(pending)

            await self.state.with_subscription_lock(id_, commit, self.env)
            committed = True
        finally:
            if not committed and not potentially_pending:
                await self.finish(id_, progress)
            # Unknown cleanup or publication preserves prepared journal plus
            # original receipt. Reaping/death cannot manufacture its success.
