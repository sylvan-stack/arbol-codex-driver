"""Cooperative normal admission before any Driver-state access.

Registry I/O is local protocol authority, not Subscription state. Every process
opens an independent component lease; no inherited lock or PID alone admits it.
"""

from __future__ import annotations

import fcntl
import os
import socket
import struct
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from contextvars import Token as ContextToken
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType
from typing import IO, cast

from .identity_protocol import (
    DOCUMENT_LIMIT,
    PrivateDirectory,
    canonical_bytes,
    canonical_uuid,
    digest,
    fresh_token,
    integer,
    invalid,
    object_fields,
    parse_bytes,
    physical_path,
    private_stat,
    relative_path,
    same_inode,
    sha256,
    token,
)
from .json_types import Json, Object
from .payload import COMPONENT, Authority, Payload, verify_authority
from .process_identity import Identity, boot_uuid, identity_record, matches, process_identity

NORMAL_FD = "ARBOL_DRIVER_ADMISSION_FD"
NORMAL_CONTEXT = "ARBOL_DRIVER_ADMISSION_CONTEXT"
AUTHORITY_ENV = (
    NORMAL_FD, NORMAL_CONTEXT, "ARBOL_DRIVER_MAINTENANCE_FD", "ARBOL_DRIVER_MAINTENANCE_CONTEXT"
)


def _read(path: Path) -> Object:
    with PrivateDirectory(physical_path(str(path.parent))) as directory:
        raw = directory.read(path.name)
    if raw is None:
        raise invalid()
    value = parse_bytes(raw)
    assert isinstance(value, dict)
    return value


def _publish(path: Path, value: Object, *, absent: bool = False) -> None:
    with PrivateDirectory(physical_path(str(path.parent))) as directory:
        if absent and directory.read(path.name) is not None:
            raise invalid()
        directory.publish(path.name, canonical_bytes(value))


def _version(value: Object) -> None:
    integer(value["version"], 1, 1)


def _context(value: Json) -> Object:
    row = object_fields(value, {
        "version", "kind", "role", "registry", "registrySha256", "component", "epoch", "boot", "invocation",
        "writer", "parent", "process", "handoff", "nonce", "payloadSha256", "acceptanceSha256", "entry",
    })
    _version(row)
    if row["kind"] != "driver-admission-context" or row["role"] not in ("main", "helper") or row["component"] != COMPONENT:
        raise invalid()
    for key in ("epoch", "invocation", "writer", "handoff", "nonce"):
        token(row[key])
    for key in ("registrySha256", "payloadSha256", "acceptanceSha256"):
        digest(row[key])
    physical_path(row["registry"])
    canonical_uuid(row["boot"])
    relative_path(row["entry"])
    identity_record(row["process"])
    parent = object_fields(row["parent"], {"writer", "pid", "startedAt"})
    token(parent["writer"])
    identity_record({"pid": parent["pid"], "startedAt": parent["startedAt"]})
    return row


def _identity(value: Object) -> Identity:
    return identity_record({"pid": value["pid"], "startedAt": value["startedAt"]})


def _writer(value: Json) -> Object:
    row = object_fields(value, {
        "version", "invocation", "writer", "parent", "component", "epoch", "payloadSha256", "boot", "pid",
        "startedAt", "phase", "contextSha256",
    })
    _version(row)
    if row["component"] != COMPONENT or row["phase"] not in ("active", "terminal"):
        raise invalid()
    for key in ("invocation", "writer", "epoch"):
        token(row[key])
    digest(row["payloadSha256"])
    canonical_uuid(row["boot"])
    _identity(row)
    if row["parent"] is not None:
        token(row["parent"])
    if row["contextSha256"] is not None:
        digest(row["contextSha256"])
    elif row["parent"] is not None:
        raise invalid()
    return row


class Frames:
    """One exact framed handshake with a single twenty-second deadline."""

    def __init__(self, descriptor: int) -> None:
        integer(descriptor, 3)
        self.socket = socket.socket(fileno=descriptor)
        try:
            if self.socket.family != socket.AF_UNIX or self.socket.type != socket.SOCK_STREAM:
                raise invalid()
            os.set_inheritable(descriptor, False)
        except BaseException:
            self.socket.close()
            raise
        self.deadline = time.monotonic() + 20

    def _timeout(self) -> None:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise invalid()
        self.socket.settimeout(remaining)

    def _read(self, count: int) -> bytes:
        data = bytearray()
        while len(data) < count:
            self._timeout()
            part = self.socket.recv(count - len(data))
            if not part:
                raise invalid()
            data.extend(part)
        return bytes(data)

    def receive(self) -> Object:
        count = struct.unpack(">I", self._read(4))[0]
        if not 0 < count <= DOCUMENT_LIMIT:
            raise invalid()
        result = parse_bytes(self._read(count))
        assert isinstance(result, dict)
        return result

    def send(self, value: Object) -> None:
        raw = canonical_bytes(value)
        self._timeout()
        self.socket.sendall(struct.pack(">I", len(raw)) + raw)

    def no_extra(self) -> None:
        self.socket.setblocking(False)
        try:
            if self.socket.recv(1, socket.MSG_PEEK):
                raise invalid()
        except BlockingIOError:
            pass

    def close(self) -> None:
        self.socket.close()


class Registry:
    def __init__(self, registry: Path) -> None:
        self.root = physical_path(str(registry))
        self.folder = self.root / COMPONENT / ".driver-admission"
        self.lock_identity: dict[str, os.stat_result] = {}
        with PrivateDirectory(self.folder):
            pass

    def open_lock(self, name: str) -> int:
        if name not in ("control.lock", "admission.lock"):
            raise invalid()
        with PrivateDirectory(self.folder) as directory:
            descriptor = os.open(name, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=directory.fd)
            try:
                self.check_lock(name, descriptor)
                return descriptor
            except BaseException:
                os.close(descriptor)
                raise

    def check_lock(self, name: str, descriptor: int) -> None:
        current = os.stat(self.folder / name, follow_symlinks=False)
        held = os.fstat(descriptor)
        private_stat(current)
        private_stat(held)
        previous = self.lock_identity.setdefault(name, current)
        if not same_inode(current, held) or not same_inode(previous, held):
            raise invalid()

    @contextmanager
    def mutex(self, deadline: float | None = None) -> Iterator[None]:
        deadline = time.monotonic() + 20 if deadline is None else deadline
        descriptor = self.open_lock("control.lock")
        try:
            while True:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise invalid() from None
                    time.sleep(min(0.01, max(0, deadline - time.monotonic())))
            self.check_lock("control.lock", descriptor)
            yield
            self.check_lock("control.lock", descriptor)
        finally:
            os.close(descriptor)

    def lease(self) -> int:
        descriptor = self.open_lock("admission.lock")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
            self.check_lock("admission.lock", descriptor)
            return descriptor
        except BaseException:
            os.close(descriptor)
            raise

    def writer_path(self, invocation: Json, writer: Json) -> Path:
        return self.folder / "writers" / token(invocation) / (token(writer) + ".json")

    def writer(self, invocation: Json, writer: Json) -> Object:
        row = _writer(_read(self.writer_path(invocation, writer)))
        if row["invocation"] != invocation or row["writer"] != writer:
            raise invalid()
        return row

    def handoff_path(self, handoff: Json) -> Path:
        return self.folder / "handoffs" / (token(handoff) + ".json")

    def control(self, context: Object, *, permit_draining: bool, gate_sha256: str | None = None) -> None:
        row = object_fields(_read(self.folder / "control.json"), {"version", "phase", "session", "epoch"})
        _version(row)
        if row["phase"] not in ("normal", "draining", "exclusive") or row["epoch"] != context["epoch"]:
            raise invalid()
        token(row["epoch"])
        if (row["phase"] == "normal") != (row["session"] is None):
            raise invalid()
        if row["session"] is not None:
            canonical_uuid(row["session"])
        if row["phase"] != "normal" and not (permit_draining and row["phase"] == "draining"):
            raise invalid()
        deployment_path = self.root / ".driver-qualification" / "deployment.json"
        with PrivateDirectory(deployment_path.parent) as directory:
            deployment = directory.read(deployment_path.name)
        if deployment is not None:
            status = object_fields(parse_bytes(deployment), {
                "version", "kind", "session", "registrySha256", "gateSha256", "callersSha256", "oldBoot", "newBoot",
                "phase", "components", "checkpoint",
            })
            _version(status)
            if status["kind"] != "driver-gate-deployment" or status["phase"] not in (
                "staged", "closed-installed", "awaiting-boot", "boot-verified", "maintaining", "complete", "failed-closed"
            ):
                raise invalid()
            if status["phase"] != "complete" and not (permit_draining and row["phase"] == "draining"):
                raise invalid()
            canonical_uuid(status["session"])
            canonical_uuid(status["oldBoot"])
            if status["newBoot"] is not None:
                canonical_uuid(status["newBoot"])
            elif status["phase"] == "complete":
                raise invalid()
            token(status["checkpoint"])
            for key in ("registrySha256", "gateSha256", "callersSha256"):
                digest(status[key])
            if (
                status["registrySha256"] != context["registrySha256"] or not isinstance(status["components"], list)
                or gate_sha256 is not None and status["gateSha256"] != gate_sha256
            ):
                raise invalid()
            names: list[str] = []
            for item in status["components"]:
                component = object_fields(item, {"component", "epoch", "launcherSha256", "closed"})
                name = component["component"]
                if not isinstance(name, str) or component["closed"] is not True:
                    raise invalid()
                token(component["epoch"])
                digest(component["launcherSha256"])
                names.append(name)
            from .payload import DRIVER_COMPONENTS

            if tuple(names) != DRIVER_COMPONENTS:
                raise invalid()
        with PrivateDirectory(self.folder) as directory:
            raw_taint = directory.read("taint.json")
        if raw_taint is not None:
            taint = object_fields(parse_bytes(raw_taint), {
                "version", "component", "epoch", "boot", "reason", "invocation", "payloadSha256"
            })
            _version(taint)
            if taint["component"] != COMPONENT or taint["reason"] != "legacy":
                raise invalid()
            for key in ("epoch", "invocation"):
                token(taint[key])
            canonical_uuid(taint["boot"])
            if taint["payloadSha256"] is not None:
                digest(taint["payloadSha256"])

    def custody_loss(self, context: Object) -> None:
        # Caller holds the mutex. Durable taint overrides otherwise normal
        # control without inventing a maintenance-session UUID.
        with PrivateDirectory(self.folder) as directory:
            previous = directory.read("taint.json")
            if previous is not None:
                with PrivateDirectory(self.folder / "archive") as archive:
                    archive.publish("taint-" + fresh_token() + ".json", previous)
            directory.publish("taint.json", canonical_bytes({
                "version": 1, "component": COMPONENT, "epoch": context["epoch"], "boot": context["boot"],
                "reason": "custody-loss", "invocation": context["invocation"], "payloadSha256": context["payloadSha256"],
            }))



def _handoff(value: Json) -> Object:
    if not isinstance(value, dict):
        raise invalid()
    names = {
        "version", "handoff", "component", "invocation", "parent", "child", "epoch", "payloadSha256", "phase",
        "nonce", "contextSha256", "role", "entry", "acceptanceSha256",
    }
    if value.get("phase") == "accepted":
        names.add("challenge")
    row = object_fields(value, names)
    _version(row)
    if row["component"] != COMPONENT or row["phase"] not in ("pending", "accepted") or row["role"] not in ("main", "helper"):
        raise invalid()
    for key in ("handoff", "invocation", "parent", "child", "epoch", "nonce"):
        token(row[key])
    for key in ("payloadSha256", "acceptanceSha256"):
        digest(row[key])
    if row["contextSha256"] is not None:
        digest(row["contextSha256"])
    if "challenge" in row:
        token(row["challenge"])
    relative_path(row["entry"])
    return row


def _pending(context: Object, context_hash: str) -> Object:
    parent = cast(Object, context["parent"])
    return {
        "version": 1, "handoff": context["handoff"], "component": COMPONENT, "invocation": context["invocation"],
        "parent": parent["writer"], "child": context["writer"], "epoch": context["epoch"],
        "payloadSha256": context["payloadSha256"], "phase": "pending", "nonce": context["nonce"],
        "contextSha256": context_hash, "role": context["role"], "entry": context["entry"],
        "acceptanceSha256": context["acceptanceSha256"],
    }


def _own_writer(context: Object, context_hash: str) -> Object:
    parent = cast(Object, context["parent"])
    process = cast(Object, context["process"])
    return {
        "version": 1, "invocation": context["invocation"], "writer": context["writer"], "parent": parent["writer"],
        "component": COMPONENT, "epoch": context["epoch"], "payloadSha256": context["payloadSha256"],
        "boot": context["boot"], "pid": process["pid"], "startedAt": process["startedAt"], "phase": "active",
        "contextSha256": context_hash,
    }


def _check_parent(registry: Registry, context: Object) -> None:
    parent = cast(Object, context["parent"])
    expected = _identity(parent)
    process = identity_record(context["process"])
    if process["pid"] != os.getpid() or os.getppid() != expected["pid"]:
        raise invalid()
    if not matches(process, parent=expected["pid"]) or not matches(expected):
        raise invalid()
    row = registry.writer(context["invocation"], parent["writer"])
    if row["phase"] != "active" or _identity(row) != expected or any(
        row[key] != context[key] for key in ("epoch", "payloadSha256", "boot", "invocation")
    ):
        raise invalid()
    if boot_uuid() != context["boot"]:
        raise invalid()


@dataclass
class Session:
    authority: Authority
    registry: Registry
    context: Object
    context_hash: str
    lease: int
    accepted: Object
    handoffs: dict[str, Object] = field(default_factory=dict)
    _activity: threading.Condition = field(default_factory=threading.Condition, repr=False)
    _spawning: int = field(default=0, init=False)
    _closing: bool = field(default=False, init=False)
    _abandon_complete: bool = field(default=False, init=False)
    _entered: bool = field(default=False, init=False)
    _context_token: ContextToken[Session | None] | None = field(default=None, init=False, repr=False)

    def __enter__(self) -> Session:
        with self._activity:
            if self._entered or self._closing or self.lease < 0:
                raise invalid()
            self.registry.check_lock("admission.lock", self.lease)
            self._entered = True
            self._context_token = _CURRENT.set(self)
        return self

    def __exit__(self, kind: type[BaseException] | None, error: BaseException | None, tb: TracebackType | None) -> None:
        try:
            # CLI entry returns only after asyncio.run has joined its tasks and
            # executor. Expected SystemExit includes failed/cancelled CLI output.
            if kind is None or kind is SystemExit:
                self.finish()
            else:
                self.abandon()
        finally:
            if self._context_token is not None:
                _CURRENT.reset(self._context_token)
                self._context_token = None
            self._entered = False

    def _check(self) -> None:
        if self.lease < 0:
            raise invalid()
        self.registry.check_lock("admission.lock", self.lease)
        self.registry.control(self.context, permit_draining=True, gate_sha256=self.authority.gate_sha256)
        if (
            not matches(identity_record(self.context["process"])) or boot_uuid() != self.context["boot"]
            or self.registry.writer(self.context["invocation"], self.context["writer"])
            != _own_writer(self.context, self.context_hash)
        ):
            raise invalid()
        current = verify_authority(
            self.registry.root, self.authority.producer,
            expected_registry_sha256=self.authority.registry_sha256,
            expected_gate_sha256=self.authority.gate_sha256,
            expected_acceptance_sha256=self.authority.acceptance_sha256,
            isolated_scope=self.registry.root,
        )
        if current != self.authority:
            raise invalid()

    def _end_spawn(self) -> None:
        with self._activity:
            if self._spawning <= 0:
                raise invalid()
            self._spawning -= 1
            self._activity.notify_all()
            if self._abandon_complete and self._spawning == 0:
                self._close_owned()

    def prepare_helper(self, entry: str) -> HelperHandoff:
        """Preregister one exact direct child; keep activity until ACK/close.

        Callers own their child/streams and must join acknowledge before close.
        Explicit nonauthority control fds may accompany pass_fds in that spawn;
        the ticket itself supplies only its one-use admission socket.
        """
        with self._activity:
            if self._closing or self.lease < 0:
                raise invalid()
            self._spawning += 1
        registered = False
        frames: Frames | None = None
        child_socket: socket.socket | None = None
        try:
            entry = relative_path(entry)
            if entry not in self.authority.producer.declaration.helpers:
                raise invalid()
            handoff, writer, nonce = fresh_token(), fresh_token(), fresh_token()
            pending: Object = {
                "version": 1, "handoff": handoff, "component": COMPONENT, "invocation": self.context["invocation"],
                "parent": self.context["writer"], "child": writer, "epoch": self.context["epoch"],
                "payloadSha256": self.context["payloadSha256"], "phase": "pending", "nonce": nonce,
                "contextSha256": None, "role": "helper", "entry": entry,
                "acceptanceSha256": self.context["acceptanceSha256"],
            }
            with self.registry.mutex():
                self._check()
                _publish(self.registry.handoff_path(handoff), pending, absent=True)
                self.handoffs[handoff] = pending
                registered = True
            parent_socket, child_socket = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
            frames = Frames(parent_socket.detach())
            integer(child_socket.fileno(), 3)
            return HelperHandoff(self, pending, frames, child_socket)
        except BaseException:
            try:
                if registered:
                    with self.registry.mutex():
                        self.registry.custody_loss(self.context)
            finally:
                try:
                    if child_socket is not None:
                        child_socket.close()
                    if frames is not None:
                        frames.close()
                finally:
                    self._end_spawn()
            raise

    def spawn_helper(
        self, arguments: list[str], *, entry: str, environment: dict[str, str] | None = None,
        cwd: Path | None = None, stdin: int | IO[bytes] | None = None,
        stdout: int | IO[bytes] | None = None, stderr: int | IO[bytes] | None = None,
        start_new_session: bool = True,
    ) -> subprocess.Popen[bytes]:
        ticket = self.prepare_helper(entry)
        try:
            child = subprocess.Popen(
                [*ticket.prefix, *arguments], env=ticket.environment(dict(os.environ) if environment is None else environment),
                cwd=cwd, pass_fds=ticket.pass_fds, close_fds=True, stdin=stdin, stdout=stdout, stderr=stderr,
                start_new_session=start_new_session,
            )
            ticket.acknowledge(child.pid)
            return child
        finally:
            ticket.close()

    def _close_owned(self) -> None:
        if self.lease >= 0:
            descriptor, self.lease = self.lease, -1
            os.close(descriptor)  # Never LOCK_UN another process's description.

    def _settle_handoffs(self) -> None:
        if _handoff(_read(self.registry.handoff_path(self.context["handoff"]))) != self.accepted:
            raise invalid()
        for handoff, expected_handoff in self.handoffs.items():
            if expected_handoff["phase"] != "accepted":
                raise invalid()
            if _handoff(_read(self.registry.handoff_path(handoff))) != expected_handoff:
                raise invalid()
            context_path = self.registry.folder / "handoffs" / (handoff + ".context.json")
            child_context = _context(_read(context_path))
            context_hash = sha256(canonical_bytes(child_context))
            if (
                context_hash != expected_handoff["contextSha256"]
                or {**_pending(child_context, context_hash), "phase": "accepted",
                    "challenge": expected_handoff["challenge"]} != expected_handoff
            ):
                raise invalid()
            expected_writer = _own_writer(child_context, context_hash)
            actual = self.registry.writer(child_context["invocation"], child_context["writer"])
            if actual not in (expected_writer, {**expected_writer, "phase": "terminal"}):
                raise invalid()
            # An accepted active helper owns its independent lease/obligation;
            # parent completion neither erases it nor claims that it exited.

    def finish(self) -> None:
        deadline = time.monotonic() + 20
        with self._activity:
            if self.lease < 0 or self._closing:
                raise invalid()
            self._closing = True
            while self._spawning and time.monotonic() < deadline:
                self._activity.wait(max(0, deadline - time.monotonic()))
            busy = bool(self._spawning)
        if busy:
            self.abandon()
            raise invalid()
        try:
            with self.registry.mutex():
                self._check()
                self._settle_handoffs()
                terminal = {**_own_writer(self.context, self.context_hash), "phase": "terminal"}
                _publish(self.registry.writer_path(self.context["invocation"], self.context["writer"]), _writer(terminal))
                self.registry.check_lock("admission.lock", self.lease)
            with self._activity:
                self._close_owned()
        except BaseException:
            self.abandon()
            raise

    def abandon(self) -> None:
        with self._activity:
            self._closing = True
        try:
            with self.registry.mutex():
                self.registry.custody_loss(self.context)
        finally:
            with self._activity:
                self._abandon_complete = True
                if self._spawning == 0:
                    self._close_owned()
                # If a timed-out spawning thread remains, retain this process's
                # lease until that thread's last protocol effect, or process
                # death. Its active record and taint remain unresolved.


@dataclass
class HelperHandoff:
    """Exact one-use direct-child ticket; an idle close preserves uncertainty."""

    parent: Session
    pending: Object
    frames: Frames
    child_socket: socket.socket
    completed: bool = False
    _closed: bool = False
    _busy: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def context_path(self) -> Path:
        return self.parent.registry.folder / "handoffs" / (token(self.pending["handoff"]) + ".context.json")

    @property
    def prefix(self) -> list[str]:
        payload = self.parent.authority.producer
        entry = relative_path(self.pending["entry"])
        if self._closed or entry not in payload.declaration.helpers:
            raise invalid()
        return [str(payload.regular_file(payload.declaration.interpreter)), "-ISB", str(payload.regular_file(entry))]

    @property
    def pass_fds(self) -> tuple[int, ...]:
        if self._closed:
            raise invalid()
        descriptor = self.child_socket.fileno()
        integer(descriptor, 3)
        return (descriptor,)

    def environment(self, inherited: dict[str, str]) -> dict[str, str]:
        environment = {key: value for key, value in inherited.items() if key not in AUTHORITY_ENV}
        environment[NORMAL_FD] = str(self.pass_fds[0])
        environment[NORMAL_CONTEXT] = str(self.context_path)
        return environment

    def _release(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        try:
            self.child_socket.close()
        finally:
            try:
                self.frames.close()
            finally:
                self.parent._end_spawn()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            if self._busy:
                raise invalid()  # Join the registry-writing worker before closing.
            self._busy = True
        try:
            if not self.completed:
                with self.parent.registry.mutex():
                    self.parent.registry.custody_loss(self.parent.context)
        finally:
            self._release()

    def acknowledge(self, pid: int) -> None:
        with self._lock:
            if self._closed or self._busy:
                raise invalid()
            self._busy = True
        parent, pending, frames = self.parent, self.pending, self.frames
        try:
            handoff, writer, nonce = (token(pending[key]) for key in ("handoff", "child", "nonce"))
            entry = relative_path(pending["entry"])
            path, context_path = parent.registry.handoff_path(handoff), self.context_path
            self.child_socket.close()
            child_identity = process_identity(pid)
            if not matches(child_identity, parent=os.getpid()):
                raise invalid()
            own = identity_record(parent.context["process"])
            context: Object = {
                **parent.context, "role": "helper", "writer": writer, "handoff": handoff, "nonce": nonce,
                "entry": entry, "parent": {"writer": parent.context["writer"], "pid": own["pid"], "startedAt": own["startedAt"]},
                "process": {"pid": child_identity["pid"], "startedAt": child_identity["startedAt"]},
            }
            _context(context)
            context_hash = sha256(canonical_bytes(context))
            with parent.registry.mutex(frames.deadline):
                parent._check()
                if _handoff(_read(path)) != pending or not matches(child_identity, parent=os.getpid()):
                    raise invalid()
                _publish(context_path, context, absent=True)
                pending = {**pending, "contextSha256": context_hash}
                _publish(path, pending)
                parent.handoffs[handoff] = pending
            frames.send({"version": 1, "type": "offer", "contextSha256": context_hash})
            ready = object_fields(frames.receive(), {"version", "type", "handoff", "nonce", "contextSha256", "challenge"})
            _version(ready)
            challenge = token(ready["challenge"])
            frame: Object = {"version": 1, "handoff": handoff, "nonce": nonce,
                             "contextSha256": context_hash, "challenge": challenge}
            if ready != {**frame, "type": "ready"}:
                raise invalid()
            expected = _own_writer(context, context_hash)
            accepted = {**pending, "phase": "accepted", "challenge": challenge}
            with parent.registry.mutex(frames.deadline):
                parent._check()
                if (
                    _handoff(_read(path)) != pending
                    or parent.registry.writer(context["invocation"], writer) != expected
                    or not matches(child_identity, parent=os.getpid())
                ):
                    raise invalid()
                _publish(path, _handoff(accepted))
            frames.send({**frame, "type": "go"})
            started = frames.receive()
            _version(started)
            if started != {**frame, "type": "started"}:
                raise invalid()
            frames.no_extra()
            with parent.registry.mutex(frames.deadline):
                parent._check()
                current = parent.registry.writer(context["invocation"], writer)
                if _handoff(_read(path)) != accepted or current not in (expected, {**expected, "phase": "terminal"}):
                    raise invalid()
                parent.handoffs[handoff] = accepted
            self.pending = accepted
            self.completed = True
        except BaseException:
            with parent.registry.mutex():
                parent.registry.custody_loss(parent.context)
            raise
        finally:
            self._release()


_CURRENT: ContextVar[Session | None] = ContextVar("codex_driver_admission", default=None)


def current_session() -> Session:
    session = _CURRENT.get()
    if session is None or session._closing or session.lease < 0:
        raise invalid()
    return session


def admit(payload: Payload, context: Path, descriptor: int, *, isolated_scope: Path | None = None) -> Session:
    frames = Frames(descriptor)
    registry: Registry | None = None
    parsed: Object | None = None
    lease = -1
    registered = False
    try:
        offer = object_fields(frames.receive(), {"version", "type", "contextSha256"})
        _version(offer)
        if offer["type"] != "offer":
            raise invalid()
        context_hash = digest(offer["contextSha256"])
        parsed = _context(_read(physical_path(str(context))))
        if sha256(canonical_bytes(parsed)) != context_hash:
            raise invalid()
        registry = Registry(physical_path(parsed["registry"]))
        if context != registry.folder / "handoffs" / (token(parsed["handoff"]) + ".context.json"):
            raise invalid()
        if parsed["payloadSha256"] != payload.declaration.payload_sha256:
            raise invalid()
        entry = relative_path(parsed["entry"])
        if (parsed["role"] == "main" and entry != payload.declaration.entry) or (
            parsed["role"] == "helper" and entry not in payload.declaration.helpers
        ):
            raise invalid()
        if physical_path(os.path.abspath(sys.argv[0])) != payload.root / entry:
            raise invalid()
        pending = _pending(parsed, context_hash)
        expected = _own_writer(parsed, context_hash)
        with registry.mutex(frames.deadline):
            registry.control(parsed, permit_draining=parsed["role"] == "helper")
            _check_parent(registry, parsed)
            if _handoff(_read(registry.handoff_path(parsed["handoff"]))) != pending:
                raise invalid()
            gate_path = registry.root / ".driver-qualification" / "gate.json"
            with PrivateDirectory(gate_path.parent) as directory:
                raw_gate = directory.read(gate_path.name)
            if raw_gate is None:
                raise invalid()
            authority = verify_authority(
                registry.root, payload, expected_registry_sha256=digest(parsed["registrySha256"]),
                expected_gate_sha256=sha256(raw_gate), expected_acceptance_sha256=digest(parsed["acceptanceSha256"]),
                isolated_scope=registry.root if isolated_scope is None else isolated_scope,
            )
            registry.control(parsed, permit_draining=parsed["role"] == "helper", gate_sha256=authority.gate_sha256)
            lease = registry.lease()
            _publish(registry.writer_path(parsed["invocation"], parsed["writer"]), expected, absent=True)
            registered = True
        challenge = fresh_token()
        frame: Object = {
            "version": 1, "handoff": parsed["handoff"], "nonce": parsed["nonce"],
            "contextSha256": context_hash, "challenge": challenge,
        }
        frames.send({**frame, "type": "ready"})
        go = frames.receive()
        _version(go)
        if go != {**frame, "type": "go"}:
            raise invalid()
        accepted = {**pending, "phase": "accepted", "challenge": challenge}
        with registry.mutex(frames.deadline):
            registry.control(parsed, permit_draining=parsed["role"] == "helper", gate_sha256=authority.gate_sha256)
            registry.check_lock("admission.lock", lease)
            _check_parent(registry, parsed)
            if (
                _handoff(_read(registry.handoff_path(parsed["handoff"]))) != accepted
                or registry.writer(parsed["invocation"], parsed["writer"]) != expected
                or _context(_read(context)) != parsed
            ):
                raise invalid()
        frames.send({**frame, "type": "started"})
        frames.no_extra()
        return Session(authority, registry, parsed, context_hash, lease, accepted)
    except BaseException:
        try:
            if registered and registry is not None and parsed is not None:
                with registry.mutex():
                    registry.custody_loss(parsed)
        finally:
            if lease >= 0:
                os.close(lease)
        raise
    finally:
        frames.close()
