"""Exclusive local maintenance checkpoints, never provider admission authority.

The entered provider handoff and independently opened stable local guard span
all state effects and final output. No native credentials, homes or account
state are copied into metadata archives. CLI integration is separate.
"""

import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from types import TracebackType

from .errors import Failure
from .identity import IdentityState, canonical_id, root_generation, state_format
from .identity_backup import (
    Archive,
    local_marker,
    metadata_name,
    metadata_names,
    preserve,
    private_directory,
    publish_bytes,
    raw_format,
    read_bytes,
    sync_directory,
    validate_source,
)
from .identity_protocol import PrivateDirectory, canonical_bytes, invalid, parse_bytes, sha256, token
from .json_types import Object, timestamp
from .maintenance import Maintenance, current_maintenance
from .state import owner_alive, parse_owner, prepare_file, read_json, with_subscription_directory_lock
from .subscriptions import parse_progress, parse_record


class Operation:
    def __init__(self, maintenance: Maintenance | None = None) -> None:
        self.maintenance = current_maintenance() if maintenance is None else maintenance
        self.directory = self.maintenance.request.state
        self.guard: IdentityState | None = None
        self.before: Archive | None = None
        self.source_hash: str | None = None

    @property
    def context(self) -> Object:
        return self.maintenance.context

    @property
    def generation(self) -> str:
        return token(self.context["generation"])

    def check(self) -> Object:
        operation = self.maintenance.recheck()
        if self.guard is None:
            raise invalid()
        self.guard.check_guard()
        private_directory(self.directory)
        return operation

    def __enter__(self) -> Operation:
        self.maintenance.recheck()  # Before even the read-only target preflight.
        if self.guard is not None:
            raise invalid()
        private_directory(self.directory)
        number = raw_format(read_bytes(self.directory / "format", limit=4096))
        flags = os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
        if number == 1:
            # Pre-identity format1 may lack a guard. The component has already
            # drained old writers; existing format2 never recreates its inode.
            flags |= os.O_CREAT
        descriptor = os.open(self.directory / "identity.guard", flags, 0o600)
        try:
            guard = IdentityState(self.directory, descriptor, number or 1, None)
            guard.check_guard()
            guard.lock(exclusive=True)
            os.fsync(descriptor)
            with PrivateDirectory(self.directory) as directory:
                os.fsync(directory.fd)
            self.guard = guard
            self.check()
            return self
        except BaseException:
            self.guard = None
            os.close(descriptor)
            raise

    def __exit__(self, kind: type[BaseException] | None, error: BaseException | None, tb: TracebackType | None) -> None:
        try:
            self.check()
        finally:
            if self.guard is not None:
                descriptor, self.guard.closed = self.guard.descriptor, True
                self.guard = None
                os.close(descriptor)  # Never LOCK_UN, unlink or replace a guard.

    def marker(self, phase: str) -> Object:
        if self.before is None:
            raise invalid()
        value: Object = {
            "version": 1,
            **{name: self.context[name] for name in (
                "component", "session", "epoch", "operation", "attempt", "payloadSha256", "generation",
            )},
            "phase": phase, "sourceSha256": self.source_hash, "backupSha256": self.before.digest,
        }
        return local_marker(value)

    def read_marker(self) -> Object | None:
        self.check()
        raw = read_bytes(self.directory / "identity-maintenance.json", limit=4096)
        return local_marker(parse_bytes(raw)) if raw is not None else None

    def write(self, name: str, raw: bytes) -> None:
        self.check()
        publish_bytes(self.directory / metadata_name(name), raw, limit=4096)
        self.check()

    def delete(self, name: str) -> None:
        self.check()
        path = self.directory / metadata_name(name)
        with PrivateDirectory(path.parent) as directory:
            directory.delete(path.name)
        self.check()

    def prepare(self, *, source: Archive | None = None, extra: list[str] | None = None) -> Archive:
        operation = self.check()
        source_hash = source.digest if source is not None else None
        if operation["sourceSha256"] != source_hash:
            raise invalid()
        before = preserve(self.directory, self.maintenance.request.backup, self.context, source_hash, extra=extra)
        if operation["backupSha256"] not in (None, before.digest):
            raise invalid()
        self.before, self.source_hash = before, source_hash
        current = self.read_marker()
        if current is None:
            self.write("identity-maintenance.json", canonical_bytes(self.marker("pending")))
        elif current not in (self.marker("pending"), self.marker("complete")):
            raise invalid()
        return before

    async def short_lock[T](self, identifier: str, change: Callable[[], Awaitable[T]]) -> T:
        self.check()
        parent = private_directory(self.directory / "subscriptions", create=True)
        directory = private_directory(parent / canonical_id(identifier), create=True)

        async def admitted_change() -> T:
            self.check()
            result = await change()
            self.check()
            return result

        return await with_subscription_directory_lock(directory, admitted_change)

    def subscriptions(self) -> list[Path]:
        self.check()
        directory = self.directory / "subscriptions"
        if not os.path.lexists(directory):
            return []
        private_directory(directory)
        result = list(directory.iterdir())
        for folder in result:
            canonical_id(folder.name)
            private_directory(folder)
        return result

    async def validate_records(self) -> None:
        """Read/validate legacy records and known owners, never reap or adopt auth."""
        self.check()
        for folder in self.subscriptions():
            value = read_json(folder / "record.json")
            if value is not None:
                parse_record(value, folder.name)
            pending = read_json(folder / "sign-in.json")
            if pending is not None:
                progress = parse_progress(pending)
                for name in ("owner", "tool"):
                    if name in progress and await owner_alive(parse_owner(progress[name])):
                        raise Failure("in_use", "An account operation still owns Driver state.")
        directory = self.directory / "runs"
        if os.path.lexists(directory):
            private_directory(directory)
            for path in directory.glob("*.json"):
                if path.name.startswith("."):
                    continue
                value = read_json(path)
                if value is None:
                    continue
                if (
                    not isinstance(value, dict) or value.get("runId") != canonical_id(path.stem)
                    or not isinstance(value.get("subscriptionId"), str) or timestamp(value.get("startedAt")) is None
                ):
                    raise invalid()
                canonical_id(str(value["subscriptionId"]))
                for name in ("owner", "tool", "cleanupOwner"):
                    if name == "owner" or name in value:
                        if await owner_alive(parse_owner(value.get(name))):
                            raise Failure("in_use", "An owned run still uses Driver state.")
        self.check()

    def validate_metadata(self, *, target: str | None = None, upgrade: bool = False) -> None:
        self.check()
        for name in metadata_names(self.directory):
            raw = read_bytes(self.directory / name, limit=4096)
            if raw is None:
                continue
            validate_source(name, raw)
            if name == "identity-upgrade.json" and not upgrade:
                raise invalid()
            if name.endswith("/identity-pending.json") and (
                target is None or name == f"subscriptions/{target}/identity-pending.json"
            ):
                raise invalid()

    async def convert(self, before: Archive, backup: Path) -> None:
        self.check()
        if before.format != 1:
            raise invalid()
        expected: Object = {"version": 1, "from": 1, "to": 2, "generation": self.generation,
                            "backup": str(backup), "backupSha256": before.digest}
        raw = read_bytes(self.directory / "identity-upgrade.json", limit=4096)
        number = state_format(self.directory)
        if raw is not None:
            validate_source("identity-upgrade.json", raw)
            if parse_bytes(raw) != expected or number not in (1, 2):
                raise invalid()
        elif number == 2 and root_generation(self.directory) == self.generation:
            return  # The exact conversion committed before acknowledgement.
        elif number != 1:
            raise invalid()
        staged = prepare_file(self.directory / "identity.json", canonical_bytes({
            "version": 1, "generation": self.generation,
        }).decode("utf-8"))
        try:
            self.write("identity-upgrade.json", canonical_bytes(expected))
            self.write("format", b"2\n")
            self.check()
            os.replace(staged, self.directory / "identity.json")
            sync_directory(self.directory)
            self.check()
            await self.validate_records()
            if state_format(self.directory) != 2 or root_generation(self.directory) != self.generation:
                raise invalid()
            self.delete("identity-upgrade.json")
        finally:
            staged.unlink(missing_ok=True)

    async def upgrade(self) -> Object:
        if self.context["operation"] != "upgrade":
            raise invalid()
        await self.validate_records()
        # Refuse newer format read-only before preservation/marker mutation.
        number = state_format(self.directory)
        self.validate_metadata(upgrade=True)
        before = self.prepare()
        if self.read_marker() == self.marker("complete"):
            return self.result()
        if number == 2 and read_bytes(self.directory / "identity-upgrade.json", limit=4096) is None:
            if root_generation(self.directory) != self.generation:
                raise invalid()
        else:
            await self.convert(before, self.maintenance.request.backup)
        return self.complete()

    def validate_settled(self, *, complete: bool) -> None:
        operation = self.check()
        if self.before is None or self.source_hash != operation["sourceSha256"]:
            raise invalid()
        repeated = Archive.load(self.maintenance.request.backup / "before")
        if repeated.digest != self.before.digest or operation["backupSha256"] not in (None, repeated.digest):
            raise invalid()
        if state_format(self.directory) != 2 or root_generation(self.directory) != self.generation:
            raise invalid()
        if read_bytes(self.directory / "identity-upgrade.json", limit=4096) is not None:
            raise invalid()
        marker = self.read_marker()
        allowed = (self.marker("complete"),) if complete else (self.marker("pending"), self.marker("complete"))
        if marker not in allowed:
            raise invalid()
        target = canonical_id(str(self.context["subscription"])) if self.context["operation"] == "identity-recover" else None
        for name in metadata_names(self.directory):
            raw = read_bytes(self.directory / name, limit=4096)
            if raw is None:
                continue
            validate_source(name, raw)
            if name.endswith("/identity-pending.json") and (
                target is None or name == f"subscriptions/{target}/identity-pending.json"
            ):
                raise invalid()
        self.check()

    def complete(self) -> Object:
        self.validate_settled(complete=False)
        self.write("identity-maintenance.json", canonical_bytes(self.marker("complete")))
        return self.result()

    def result(self) -> Object:
        self.validate_settled(complete=True)
        maintenance: Object = {name: self.context[name] for name in (
            "component", "session", "epoch", "operation", "attempt", "payloadSha256",
        )}
        maintenance["stateDirectorySha256"] = sha256(str(self.directory).encode("utf-8"))
        if self.context["operation"] == "identity-recover":
            maintenance["subscription"] = canonical_id(str(self.context["subscription"]))
        result: Object = {"version": 1, "format": 2, "generation": self.generation, "maintenance": maintenance}
        canonical_bytes(result)
        return result
