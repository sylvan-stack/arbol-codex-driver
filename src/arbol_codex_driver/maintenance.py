"""Exclusive administrative handoff verification, before target-state access.

This module consumes a live qualified provider handoff. It does not drain
custody, convert/repair state, write operation/result receipts or reopen a gate.
"""

from __future__ import annotations

import fcntl
import os
import re
import sys
from contextvars import ContextVar
from contextvars import Token as ContextToken
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType

from .admission import Registry
from .identity_protocol import (
    PrivateDirectory,
    canonical_uuid,
    digest,
    integer,
    invalid,
    object_fields,
    parse_bytes,
    physical_path,
    sha256,
    token,
)
from .json_types import Json, Object
from .payload import COMPONENT, Authority, Payload, registry_identity, verify_authority

OPERATIONS = ("upgrade", "identity-reset", "restore", "identity-recover")
_CONTEXT_FIELDS = {
    "version", "kind", "component", "session", "epoch", "gateSha256", "payloadSha256", "stateDirectory",
    "operation", "attempt", "receiptSha256", "registry", "acceptanceSha256", "generation",
}


def _read(path: Path) -> tuple[bytes, Object]:
    with PrivateDirectory(physical_path(str(path.parent))) as directory:
        raw = directory.read(path.name)
    if raw is None:
        raise invalid()
    result = parse_bytes(raw)
    assert isinstance(result, dict)
    return raw, result


def _context(value: Json) -> Object:
    if not isinstance(value, dict):
        raise invalid()
    fields = _CONTEXT_FIELDS | ({"subscription"} if value.get("operation") == "identity-recover" else set())
    row = object_fields(value, fields)
    integer(row["version"], 1, 1)
    if row["kind"] != "driver-state-context" or row["component"] != COMPONENT or row["operation"] not in OPERATIONS:
        raise invalid()
    canonical_uuid(row["session"])
    for name in ("epoch", "attempt", "generation"):
        token(row[name])
    for name in ("gateSha256", "payloadSha256", "receiptSha256", "acceptanceSha256"):
        digest(row[name])
    physical_path(row["registry"])
    target = row["stateDirectory"]
    if not isinstance(target, str) or not Path(target).is_absolute() or str(Path(target)) != target:
        raise invalid()
    if "subscription" in row and (
        not isinstance(row["subscription"], str)
        or re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}", row["subscription"]) is None
    ):
        raise invalid()
    return row


@dataclass(frozen=True)
class Request:
    operation: str
    state: Path
    receipt: Path
    backup: Path
    source: Path | None
    subscription: str | None


def _request(arguments: list[str], context: Object, folder: Path) -> Request:
    operation = str(context["operation"])
    state = Path(str(context["stateDirectory"]))
    receipt = folder / "maintenance.json"
    if arguments[:4] != ["--state-dir", str(state), "state", operation]:
        raise invalid()
    values: dict[str, str] = {}
    flags: set[str] = set()
    words = arguments[4:]
    while words:
        key, *words = words
        if key in ("--confirm-quiescent", "--retire"):
            if key in flags:
                raise invalid()
            flags.add(key)
        elif key in ("--from-format", "--maintenance", "--backup", "--source", "--subscription"):
            if key in values or not words or not words[0] or words[0].startswith("--"):
                raise invalid()
            values[key], *words = words
        else:
            raise invalid()
    required = {"--maintenance", "--backup"}
    if operation == "upgrade":
        required.add("--from-format")
    if operation == "restore":
        required.add("--source")
    if operation == "identity-recover":
        required.add("--subscription")
    if set(values) != required or flags != ({"--confirm-quiescent", "--retire"} if operation == "identity-recover"
                                           else {"--confirm-quiescent"}):
        raise invalid()
    if values["--maintenance"] != str(receipt):
        raise invalid()
    backup = Path(values["--backup"])
    source = Path(values["--source"]) if operation == "restore" else None
    subscription = str(context["subscription"]) if operation == "identity-recover" else None
    suffix: list[str]
    if operation == "upgrade":
        if values["--from-format"] != "1":
            raise invalid()
        suffix = ["--from-format", "1", "--confirm-quiescent", "--maintenance", str(receipt), "--backup", str(backup)]
    elif operation == "identity-reset":
        suffix = ["--confirm-quiescent", "--maintenance", str(receipt), "--backup", str(backup)]
    elif operation == "restore":
        suffix = ["--source", str(source), "--backup", str(backup), "--confirm-quiescent", "--maintenance", str(receipt)]
    else:
        if values["--subscription"] != subscription:
            raise invalid()
        assert subscription is not None
        suffix = ["--subscription", subscription, "--retire", "--confirm-quiescent", "--maintenance", str(receipt),
                  "--backup", str(backup)]
    if arguments != ["--state-dir", str(state), "state", operation, *suffix]:
        raise invalid()
    return Request(operation, state, receipt, backup, source, subscription)


@dataclass
class Maintenance:
    registry: Registry
    authority: Authority
    context: Object
    context_path: Path
    context_bytes: bytes
    request: Request
    descriptor: int
    _entered: bool = field(default=False, init=False)
    _context_token: ContextToken[Maintenance | None] | None = field(default=None, init=False, repr=False)

    @property
    def session_folder(self) -> Path:
        return self.registry.folder / "sessions" / canonical_uuid(self.context["session"])

    def _exclusive(self) -> None:
        integer(self.descriptor, 3)
        self.registry.check_lock("admission.lock", self.descriptor)
        if fcntl.fcntl(self.descriptor, fcntl.F_GETFL) & os.O_ACCMODE != os.O_RDWR:
            raise invalid()
        fcntl.flock(self.descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        probe = self.registry.open_lock("admission.lock")
        try:
            try:
                fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                pass
            else:
                raise invalid()
        finally:
            os.close(probe)  # Never LOCK_UN the parent's shared description.

    def _closed(self) -> Object:
        _, control = _read(self.registry.folder / "control.json")
        object_fields(control, {"version", "phase", "session", "epoch"})
        integer(control["version"], 1, 1)
        if control != {"version": 1, "phase": "exclusive", "session": self.context["session"], "epoch": self.context["epoch"]}:
            raise invalid()
        raw_receipt, receipt = _read(self.request.receipt)
        object_fields(receipt, {"version", "kind", "component", "session", "epoch", "phase", "gateSha256"})
        integer(receipt["version"], 1, 1)
        if receipt != {
            "version": 1, "kind": "driver-state-maintenance", "component": COMPONENT,
            "session": self.context["session"], "epoch": self.context["epoch"], "phase": "exclusive",
            "gateSha256": self.context["gateSha256"],
        } or sha256(raw_receipt) != self.context["receiptSha256"]:
            raise invalid()
        with PrivateDirectory(self.registry.folder) as directory:
            if directory.read("taint.json") is not None:
                raise invalid()
        _, operation = _read(self.session_folder / "operation.json")
        object_fields(operation, set(self.context) | {"phase", "sourceSha256", "backupSha256"})
        # Validate integer/schema types, not only Python equality (True != a
        # protocol integer even though dict equality considers True == 1).
        nested = _context({key: operation[key] for key in self.context})
        if nested != self.context or operation["phase"] != "pending":
            raise invalid()
        for name in ("sourceSha256", "backupSha256"):
            if operation[name] is not None:
                digest(operation[name])
        if (self.request.operation == "restore") != (operation["sourceSha256"] is not None):
            raise invalid()
        raw_context, repeated = _read(self.context_path)
        if raw_context != self.context_bytes or _context(repeated) != self.context:
            raise invalid()
        return operation

    def check(self) -> Object:
        """Recheck under the component mutex; caller retains inherited EX lease."""
        self._exclusive()
        operation = self._closed()
        current = verify_authority(
            self.registry.root, self.authority.producer,
            expected_registry_sha256=self.authority.registry_sha256,
            expected_gate_sha256=self.authority.gate_sha256,
            expected_acceptance_sha256=self.authority.acceptance_sha256,
            isolated_scope=self.registry.root,
        )
        if current != self.authority:
            raise invalid()
        self.registry.check_lock("admission.lock", self.descriptor)
        return operation

    def recheck(self) -> Object:
        """Local algorithms may use only this invocation's entered handoff."""
        if current_maintenance() is not self:
            raise invalid()
        with self.registry.mutex():
            return self.check()

    def __enter__(self) -> Maintenance:
        if self._entered or self.descriptor < 0 or _CURRENT.get() is not None:
            raise invalid()
        with self.registry.mutex():
            self.check()
        self._context_token = _CURRENT.set(self)
        self._entered = True
        return self

    def __exit__(self, kind: type[BaseException] | None, error: BaseException | None, tb: TracebackType | None) -> None:
        try:
            with self.registry.mutex():
                self.check()
        finally:
            if self._context_token is not None:
                _CURRENT.reset(self._context_token)
                self._context_token = None
            self._entered = False
            if self.descriptor >= 0:
                descriptor, self.descriptor = self.descriptor, -1
                os.close(descriptor)


_CURRENT: ContextVar[Maintenance | None] = ContextVar("codex_driver_maintenance", default=None)


def current_maintenance() -> Maintenance:
    result = _CURRENT.get()
    if result is None or not result._entered or result.descriptor < 0:
        raise invalid()
    return result


def admit(payload: Payload, context: Path, descriptor: int, *, isolated_scope: Path | None = None) -> Maintenance:
    integer(descriptor, 3)
    os.set_inheritable(descriptor, False)
    try:
        if physical_path(os.path.abspath(sys.argv[0])) != payload.regular_file(payload.declaration.entry):
            raise invalid()
        context = physical_path(str(context))
        raw, value = _read(context)
        parsed = _context(value)
        registry = Registry(physical_path(parsed["registry"]))
        session_folder = registry.folder / "sessions" / canonical_uuid(parsed["session"])
        if context != session_folder / "contexts" / (token(parsed["attempt"]) + ".json"):
            raise invalid()
        if parsed["payloadSha256"] != payload.declaration.payload_sha256:
            raise invalid()
        request = _request(sys.argv[1:], parsed, registry.folder)
        with registry.mutex():
            authority = verify_authority(
                registry.root, payload, expected_registry_sha256=registry_identity(registry.root),
                expected_gate_sha256=digest(parsed["gateSha256"]),
                expected_acceptance_sha256=digest(parsed["acceptanceSha256"]),
                isolated_scope=registry.root if isolated_scope is None else isolated_scope,
            )
            result = Maintenance(registry, authority, parsed, context, raw, request, descriptor)
            result.check()
            # Only after the live handoff is proven do canonical/private target
            # and archive checks occur. No target payload contents are read.
            state = physical_path(str(request.state))
            with PrivateDirectory(state):
                pass
            paths = [request.backup, *([request.source] if request.source is not None else [])]
            for path in paths:
                str(path).encode("utf-8", "strict")
                actual = physical_path(str(path))
                with PrivateDirectory(actual):
                    pass
                if (
                    actual.is_relative_to(state) or state.is_relative_to(actual)
                    or actual.is_relative_to(registry.root) or registry.root.is_relative_to(actual)
                ):
                    raise invalid()
            if request.source is not None and (
                request.source.is_relative_to(request.backup) or request.backup.is_relative_to(request.source)
            ):
                raise invalid()
            if physical_path(str(request.receipt)) != request.receipt:
                raise invalid()
        return result
    except BaseException:
        os.close(descriptor)
        raise
