"""Exclusive local maintenance checkpoints, never provider admission authority.

The entered provider handoff and independently opened stable local guard span
all state effects and final output. No native credentials, homes or account
state are copied into metadata archives. CLI integration is separate.
"""

import os
from types import TracebackType

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
    validate_source,
)
from .identity_protocol import PrivateDirectory, canonical_bytes, invalid, parse_bytes, sha256, token
from .json_types import Object
from .maintenance import Maintenance, current_maintenance


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
