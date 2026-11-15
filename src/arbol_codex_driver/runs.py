import asyncio
import builtins
import os
import re
import shutil
import signal
import time
from pathlib import Path

from .continuity import Chats, digest
from .errors import Failure
from .identity import LifetimeSnapshot, lifetime_matches
from .identity_protocol import token
from .json_types import Object, dumps, now, timestamp
from .process_groups import collect_process_groups, end_process_groups
from .state import (
    Owner,
    State,
    fixed_wait,
    owner_alive,
    owner_json,
    parse_owner,
    prepare_file,
    process_owner,
    ps_time,
    read_json,
    write_json,
)


def same_reservation(a: Object, b: Object) -> bool:
    return all(a.get(key) == b.get(key) for key in ("runId", "subscriptionId", "startedAt", "owner", "lifetime"))


class Runs:
    def __init__(self, state: State, env: dict[str, str] | None = None) -> None:
        self.state, self.env = state, dict(os.environ) if env is None else env

    def path(self, id_: str) -> Path:
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}", id_):
            raise Failure("invalid_input", "The run identifier is not a safe file name.")
        return self.state.directory / "runs" / (id_ + ".json")

    def record(self, id_: str) -> Object | None:
        value = read_json(self.path(id_))
        if value is None:
            return None
        if (
            not isinstance(value, dict)
            or value.get("runId") != id_
            or not isinstance(value.get("subscriptionId"), str)
            or timestamp(value.get("startedAt")) is None
        ):
            raise Failure("internal", "Malformed run record.")
        self.state.subscription(str(value["subscriptionId"]))
        for key in ("owner", "tool", "cleanupOwner"):
            if key == "owner" or key in value:
                parse_owner(value.get(key))
        if "chatKey" in value and (
            not isinstance(value["chatKey"], str) or not re.fullmatch("[a-f0-9]{64}", str(value["chatKey"]))
        ):
            raise Failure("internal", "Malformed run chat key.")
        if "continuedConversation" in value and (
            not isinstance(value["continuedConversation"], str) or not value["continuedConversation"]
        ):
            raise Failure("internal", "Malformed run conversation.")
        if "lifetime" in value:
            lifetime = LifetimeSnapshot.parse(value["lifetime"])
            if lifetime.subscription != value["subscriptionId"]:
                raise Failure("internal", "Run lifetime names another Subscription.")
        if "continuedMapRevision" in value:
            token(value["continuedMapRevision"])
        return value

    async def list(self) -> list[Object]:
        self.state.clear_unfinished_writes()
        result: list[Object] = []
        for file in (self.state.directory / "runs").glob("*.json"):
            if file.name.startswith("."):
                continue
            record = self.record(file.stem)
            if record is not None:
                if await owner_alive(parse_owner(record.get("owner"))):
                    result.append(record)
                else:
                    await self.recover(record)
        return result

    async def orphan_groups(self, record: Object) -> builtins.list[Owner]:
        directory = self.state.directory / "tmp" / str(record["runId"])
        tool = parse_owner(record["tool"]) if "tool" in record else None
        if tool is None:
            try:
                lines = (directory / "tool-owner.txt").read_text().strip().splitlines()
            except FileNotFoundError:
                lines = []
            if lines:
                if len(lines) != 2 or re.fullmatch(r"[1-9][0-9]*", lines[0]) is None:
                    raise Failure("internal", "Malformed tool process ledger.")
                tool = {"pid": int(lines[0]), "startedAt": ps_time(lines[1])}
        ledger = read_json(directory / "shell-owners.json")
        if ledger is not None and not isinstance(ledger, list):
            raise Failure("internal", "Malformed shell process ledger.")
        groups = [parse_owner(item) for item in ledger] if isinstance(ledger, list) else []
        if tool is not None:
            groups.extend(await collect_process_groups(tool))
        return groups

    async def recover(self, stale: Object, deadline: float | None = None) -> None:
        deadline = deadline if deadline is not None else time.monotonic() + fixed_wait(20000, self.env)
        owner = await process_owner(os.getpid())
        if owner is None:
            raise Failure("internal", "Cannot identify the run cleanup owner.")
        id_, subscription_id = str(stale["runId"]), str(stale["subscriptionId"])
        while True:

            async def claim() -> Object | str | None:
                current = self.record(id_)
                if (
                    current is None
                    or not same_reservation(current, stale)
                    or await owner_alive(parse_owner(current.get("owner")))
                ):
                    return None
                if "cleanupOwner" in current and await owner_alive(parse_owner(current["cleanupOwner"])):
                    return "waiting"
                current["cleanupOwner"] = owner_json(owner)
                self.save(current)
                return current

            claimed = await self.state.with_subscription_lock(subscription_id, claim, self.env)
            if claimed is None:
                return
            if claimed == "waiting":
                if time.monotonic() >= deadline:
                    raise Failure("internal", "Another call did not finish recovering the run.")
                await asyncio.sleep(fixed_wait(50, self.env))
                continue
            assert isinstance(claimed, dict)
            claimed_record: Object = claimed

            def owned(current: Object | None, claimed: Object = claimed_record) -> bool:
                return (
                    current is not None
                    and same_reservation(current, claimed)
                    and current.get("cleanupOwner") == owner_json(owner)
                )

            try:
                remaining = await end_process_groups(
                    await self.orphan_groups(claimed),
                    min(deadline, time.monotonic() + fixed_wait(10000, self.env)),
                    time.monotonic() + fixed_wait(2000, self.env),
                )
                if remaining:
                    raise Failure(
                        "internal",
                        "Cannot end orphaned run process groups: "
                        + ", ".join(str(group["pid"]) for group in remaining)
                        + ".",
                    )
                current = self.record(id_)
                if not owned(current) or current is None or await owner_alive(parse_owner(current.get("owner"))):
                    return
                shutil.rmtree(self.state.directory / "tmp" / id_, ignore_errors=True)

                async def remove(claimed: Object = claimed_record) -> None:
                    current = self.record(id_)
                    if not owned(current) or current is None or await owner_alive(parse_owner(current.get("owner"))):
                        return
                    lifetime = LifetimeSnapshot.parse(claimed["lifetime"]) if "lifetime" in claimed else None
                    if (
                        "chatKey" in claimed and "continuedConversation" in claimed
                        and lifetime_matches(self.state.assert_admitted(), subscription_id, lifetime)
                    ):
                        chats = Chats(self.state)
                        entry = chats.entry(subscription_id, str(claimed["chatKey"]))
                        expected = claimed.get("continuedMapRevision")
                        revision = expected if isinstance(expected, str) else None
                        if (
                            entry is not None and entry["conversation"] == claimed["continuedConversation"]
                            and chats.matches(subscription_id, entry, lifetime, revision)
                        ):
                            chats.remove(subscription_id, str(claimed["chatKey"]))
                    self.remove(id_, claimed)

                await self.state.with_subscription_lock(subscription_id, remove, self.env)
            except Exception:

                async def release() -> None:
                    current = self.record(id_)
                    if owned(current) and current is not None:
                        current.pop("cleanupOwner", None)
                        self.save(current)

                await self.state.with_subscription_lock(subscription_id, release, self.env)
                raise
            return

    async def reserve(
        self, run_id: str, subscription_id: str, labels: Object | None = None, chat_session_id: str | None = None,
        *, lifetime: LifetimeSnapshot | None = None,
    ) -> Object:
        if not lifetime_matches(self.state.assert_admitted(), subscription_id, lifetime):
            raise Failure("in_use", "The Subscription lifetime changed before run reservation.")
        owner = await process_owner(os.getpid())
        if owner is None:
            raise Failure("internal", "Cannot identify the run owner.")
        record: Object = {
            "runId": run_id,
            "subscriptionId": subscription_id,
            "owner": owner_json(owner),
            "startedAt": now(),
        }
        if lifetime is not None:
            record["lifetime"] = lifetime.document()
        if labels is not None:
            record["labels"] = labels
        if chat_session_id is not None:
            record["chatKey"] = digest(chat_session_id)
        path = self.path(run_id)
        temporary = prepare_file(path, dumps(record) + "\n")
        try:
            os.link(temporary, path)
        except FileExistsError:
            raise Failure("in_use", "That run identifier is already in use.") from None
        finally:
            temporary.unlink(missing_ok=True)
        return record

    def save(self, record: Object) -> None:
        # Caller holds the short lock. Exact reservation bookkeeping survives
        # lifetime retirement so orphan process cleanup remains possible.
        current = self.record(str(record["runId"]))
        if current is None or not same_reservation(current, record):
            raise Failure("in_use", "Another run reservation took its place.")
        write_json(self.path(str(record["runId"])), record)

    async def update(self, record: Object) -> None:
        async def change() -> None:
            self.save(record)

        await self.state.with_subscription_lock(str(record["subscriptionId"]), change, self.env)

    def remove(self, id_: str, reservation: Object) -> None:
        current = self.record(id_)
        if current is not None and same_reservation(current, reservation):
            self.path(id_).unlink(missing_ok=True)

    async def finish(self, reservation: Object) -> None:
        async def change() -> None:
            self.remove(str(reservation["runId"]), reservation)

        await self.state.with_subscription_lock(str(reservation["subscriptionId"]), change, self.env)

    async def stop(self, id_: str) -> None:
        self.path(id_)
        record = next((item for item in await self.list() if item["runId"] == id_), None)
        if record is None:
            return
        owner = parse_owner(record.get("owner"))
        if await owner_alive(owner):
            try:
                os.kill(owner["pid"], signal.SIGTERM)
            except ProcessLookupError:
                pass
        deadline = time.monotonic() + fixed_wait(20000, self.env)
        while True:
            current = self.record(id_)
            if current is None or not same_reservation(current, record):
                return
            if not await owner_alive(owner):
                await self.recover(current, deadline)
                return
            if time.monotonic() >= deadline:
                raise Failure("in_use", "The run did not stop within twenty seconds.")
            await asyncio.sleep(fixed_wait(50, self.env))
