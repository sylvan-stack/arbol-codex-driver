"""Prospective Codex H1/full-unit support. No import-time I/O, CLI or admission shortcut.

Call only from the fixed admitted whole runner after independent body admission.
Actual runner callbacks supply every local result; reports never mean gate success.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import selectors
import signal
import socket
import stat
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from types import FrameType, TracebackType
from typing import Any, Literal

from arbol_codex_driver.admission import HelperHandoff, Session, current_session
from arbol_codex_driver.errors import Failure
from arbol_codex_driver.identity_protocol import PrivateDirectory, token
from arbol_codex_driver.process_identity import Identity, identity_record, inspect, matches, process_identity

Object = dict[str, Any]
COMPONENT = "arbol-codex-driver"
H1_ID = "tests/top/test_top_subscription_identity.py::HelperSpanTests.test_helper_independent_lease"
H1_EXTERNAL = "H1-span-completion"
LocalStatus = Literal["passed", "failed", "skipped", "unavailable", "pending"]


class FixtureFailure(RuntimeError):
    """Retain failed evidence/real custody; never promote a partial check."""


def require(value: bool, message: str) -> None:
    if not value:
        raise FixtureFailure(message)


def canonical(value: object, *, limit: int = 4096) -> bytes:
    raw = (json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                      separators=(",", ":")) + "\n").encode("utf-8", "strict")
    require(0 < len(raw) <= limit, "Fixture document exceeds its bound.")
    return raw


def document(raw: bytes, *, limit: int = 4096) -> Object:
    require(0 < len(raw) <= limit, "Fixture input exceeds its bound.")

    def pairs(items: list[tuple[str, Any]]) -> Object:
        value: Object = {}
        for name, item in items:
            require(name not in value, "Duplicate fixture field.")
            value[name] = item
        return value

    def nonfinite(value: str) -> None:
        raise FixtureFailure("Nonfinite fixture number.")

    value = json.loads(raw.decode("utf-8", "strict"), object_pairs_hook=pairs, parse_constant=nonfinite)
    require(isinstance(value, dict), "Expected a fixture object.")
    return dict(value)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def identities(names: Sequence[str]) -> tuple[str, ...]:
    require(0 < len(names) <= 4096 and all(isinstance(name, str) and 0 < len(name.encode()) <= 512 for name in names)
            and len(set(names)) == len(names), "Invalid full static inventory identities.")
    return tuple(names)


class FixtureRoot:
    """Retain every private namespace inode; accept no caller pathname."""

    def __init__(self, session: Session, case: str) -> None:
        require(re.fullmatch(r"[0-9a-f]{32}", case, re.ASCII) is not None, "Invalid independent fixture case.")
        session._check()
        self.session, self.case = session, case
        invocation = token(session.context["invocation"])
        self.parents: list[tuple[Path, int, int]] = []
        with PrivateDirectory(session.registry.root) as registry:
            self.parents.append((session.registry.root, registry.info.st_dev, registry.info.st_ino))
        path = session.registry.root / ".driver-qualification"
        with PrivateDirectory(path) as parent:
            self.parents.append((path, parent.info.st_dev, parent.info.st_ino))
        for name, exclusive in (("fixtures", False), (invocation, False), (case, True)):
            with PrivateDirectory(path) as parent:
                try:
                    os.mkdir(name, 0o700, dir_fd=parent.fd)
                    os.fsync(parent.fd)
                except FileExistsError:
                    require(not exclusive, "Fixture cases cannot be reused.")
            path = path / name
            with PrivateDirectory(path) as current:
                self.parents.append((path, current.info.st_dev, current.info.st_ino))
        self.path = path
        self.publish(".fixture-owner.json", canonical({"version": 1, "case": case, "component": COMPONENT,
            "invocation": invocation, "parentWriter": token(session.context["writer"]),
            "payloadSha256": session.authority.producer.declaration.payload_sha256}))

    def check(self) -> None:
        self.session._check()
        self.check_namespace()

    def check_namespace(self) -> None:
        """OS-only fixture-data preservation, never a State/admission bypass."""
        for path, device, inode in self.parents:
            with PrivateDirectory(path) as current:
                require((current.info.st_dev, current.info.st_ino) == (device, inode), "Fixture namespace replaced.")

    def publish(self, name: str, raw: bytes, *, limit: int = 4096) -> None:
        self.check()
        self._write_data(name, raw, limit=limit)
        self.check()

    def preserve_failure(self, raw: bytes) -> None:
        # Sole fixed DATA basename, not State/registry/context/terminal output.
        # An ACK failure may taint normal admission before these raw bytes can
        # be preserved; original private namespace identities still must hold.
        self._write_data("failed-h1-evidence.json", raw, limit=4 * 1024 * 1024)

    def _write_data(self, name: str, raw: bytes, *, limit: int) -> None:
        require(re.fullmatch(r"[a-z0-9.][a-z0-9_.-]{0,95}", name, re.ASCII) is not None
                and len(raw) <= limit, "Invalid bounded private evidence.")
        self.check_namespace()
        with PrivateDirectory(self.path) as directory:
            fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                         0o600, dir_fd=directory.fd)
            try:
                view = memoryview(raw)
                while view:
                    count = os.write(fd, view)
                    require(count > 0, "Private evidence write closed.")
                    view = view[count:]
                os.fsync(fd)
                held = os.fstat(fd)
                named = os.stat(name, dir_fd=directory.fd, follow_symlinks=False)
                require((held.st_dev, held.st_ino) == (named.st_dev, named.st_ino)
                        and held.st_nlink == named.st_nlink == 1, "Evidence identity/link changed.")
                os.fsync(directory.fd)
            finally:
                os.close(fd)
        self.check_namespace()

    def read(self, name: str, *, limit: int = 4096) -> bytes:
        self.check()
        with PrivateDirectory(self.path) as directory:
            raw = directory.read(name, limit)
            require(raw is not None, "Missing retained fixture bytes.")
            require(os.stat(name, dir_fd=directory.fd, follow_symlinks=False).st_nlink == 1,
                    "Hard-linked fixture evidence refuses.")
        assert raw is not None
        return raw


class SuiteControl:
    """Duplicate stdio DATA only; no control description reaches descendants."""

    def __init__(self, fixture: FixtureRoot) -> None:
        self.fixture = fixture
        self.control: list[int] = []
        self.closed = False
        try:
            sys.stdout.flush()
            sys.stderr.flush()
            for number in (0, 1, 2):
                fd = os.dup(number)
                os.set_inheritable(fd, False)
                self.control.append(fd)
            fixture.check()
            with PrivateDirectory(fixture.path) as directory:
                outputs: list[int] = []
                null = os.open(os.devnull, os.O_RDONLY | os.O_CLOEXEC)
                try:
                    for name in ("runner.stdout", "runner.stderr"):
                        outputs.append(os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                                               0o600, dir_fd=directory.fd))
                    for source, destination in ((null, 0), (outputs[0], 1), (outputs[1], 2)):
                        os.dup2(source, destination)
                    os.fsync(directory.fd)
                finally:
                    os.close(null)
                    for fd in outputs:
                        os.close(fd)
            require(all(not os.get_inheritable(fd) for fd in self.control), "Control became inheritable.")
            os.set_blocking(self.control[0], False)
            os.set_blocking(self.control[1], False)
        except BaseException as original:
            try:
                self.close()
            except BaseException as error:
                original.add_note("Suite control setup cleanup: " + type(error).__name__)
            raise

    def ready(self, report_sha256: str, *, deadline: float) -> None:
        require(not self.closed and re.fullmatch(r"[0-9a-f]{64}", report_sha256, re.ASCII) is not None,
                "Invalid readiness hash.")
        raw = canonical({"version": 1, "kind": "helper-span-ready", "case": self.fixture.case,
                         "reportSha256": report_sha256})
        view = memoryview(raw)
        with selectors.DefaultSelector() as selector:
            selector.register(self.control[1], selectors.EVENT_WRITE)
            while view:
                remaining = deadline - time.monotonic()
                require(remaining > 0, "Suite readiness deadline exceeded.")
                if selector.select(min(.05, remaining)):
                    try:
                        count = os.write(self.control[1], view)
                    except BlockingIOError:
                        continue
                    require(count > 0, "Suite readiness endpoint closed.")
                    view = view[count:]

    def close(self) -> None:
        errors: list[str] = []
        for fd in self.control:
            try:
                os.close(fd)
            except BaseException as error:
                errors.append(type(error).__name__)
        self.control.clear()
        self.closed = True
        require(not errors, "Suite data closure unresolved: " + ",".join(errors))


class CodexH1Support:
    """Static whole-runner result/report/ticket lifecycle; no case dispatcher.

    ordered/pending come from the admitted full schedule, never argv/env/filter.
    Actual runner callbacks must record real assertion outcomes. Ordinary gate
    adapters and the actor/local case are separate future bodies, unwired here.
    """

    def __init__(self, *, case: str, ordered: Sequence[str], pending: Sequence[str]) -> None:
        self.session = current_session()
        self.session._check()
        require(self.session.context["role"] == "helper" and self.session.context["entry"] == "scripts/check_build.py"
                and sys.argv[1:] == ["unit"]
                and Path(sys.argv[0]) == self.session.authority.producer.regular_file("scripts/check_build.py"),
                "Only the fixed admitted zero-tail whole-unit runner may own this support.")
        require(all(stat.S_ISFIFO(os.fstat(fd).st_mode) or stat.S_ISSOCK(os.fstat(fd).st_mode) for fd in (0, 1, 2)),
                "Whole-unit control must use owned data pipes/sockets, never an owner terminal.")
        self.ordered, self.pending = identities(ordered), identities(pending)
        require(self.ordered[-1] == H1_ID and H1_EXTERNAL in self.pending, "H1 must be the final full-local case.")
        payload = self.session.authority.producer
        require("tests/identity_actor.py" in payload.declaration.helpers, "Missing actual declared H1 helper.")
        with payload.regular_file("test-tiers.json").open("rb") as source:
            raw = source.read(1024 * 1024 + 1)
        inventory = document(raw, limit=1024 * 1024)
        require(isinstance(inventory.get("tests"), list), "Missing full inventory.")
        active: list[str] = []
        for row in inventory["tests"]:
            require(isinstance(row, dict), "Invalid inventory row.")
            if row.get("tier") == "top":
                require(row.get("status") == "active" and isinstance(row.get("id"), str), "Disabled/malformed top case.")
                active.append(row["id"])
        require(len(set(active)) == len(active) and set(active) == set(self.ordered), "Shortened/extra full-top schedule.")
        self.inventory_raw = raw
        self.fixture = FixtureRoot(self.session, case)
        self.rows: list[Object] = []
        self.child: subprocess.Popen[bytes] | None = None
        self.child_owner: Identity | None = None
        self.ticket: HelperHandoff | None = None
        self.channel: socket.socket | None = None
        self.selector: selectors.BaseSelector | None = None
        self.buffers = {name: bytearray() for name in ("stdout", "stderr", "actor", "suite")}
        self.reads: set[str] = set()
        self.pipe_eof: set[str] = set()
        self.completed = False
        self.h1_started = False
        self.end = 0.0
        self.actor_consumed = False
        self.suite_consumed = False
        self.failure_preservation_attempted = False
        self.cleanup_finished = False
        self.cleanup_errors: list[str] = []
        self.failed_output: dict[str, Object] = {}
        self.short_lock_origins: tuple[tuple[str, int, int, int, int], ...] | None = None
        self.console = SuiteControl(self.fixture)  # Last owned-resource setup.

    def __enter__(self) -> CodexH1Support:
        return self

    def __exit__(self, kind: type[BaseException] | None, error: BaseException | None,
                 traceback: TracebackType | None) -> None:
        try:
            if error is None and self.completed:
                try:
                    self.close_before_session_finish()
                except BaseException as final_error:
                    failures = self.abort_before_session_finish()
                    final_error.add_note("Positive finalization cleanup: " + ",".join(failures))
                    raise
            else:
                failures = self.abort_before_session_finish()
                if error is None:
                    raise FixtureFailure("Incomplete local phase: " + ",".join(failures))
                if failures:
                    error.add_note("Full-runner failure cleanup: " + ",".join(failures))
        except BaseException as cleanup_error:
            if error is None:
                raise
            error.add_note("Suite finalization failed: " + type(cleanup_error).__name__)

    def record(self, case_id: str, status: LocalStatus, result: bytes | None) -> None:
        require(not self.h1_started and len(self.rows) < len(self.ordered) - 1
                and self.ordered[len(self.rows)] == case_id, "Missing/duplicate/out-of-order local result.")
        require(status in ("passed", "failed", "skipped", "unavailable", "pending")
                and (result is None) == (status == "pending"), "Invalid local status/result union.")
        result_hash = None
        if result is not None:
            receipt = canonical({"version": 1, "kind": "abr38-actual-local-result", "id": case_id,
                                 "status": status, "resultHex": result.hex()}, limit=1024 * 1024)
            result_hash = sha(receipt)
            self.fixture.publish("result-" + result_hash + ".json", receipt, limit=1024 * 1024)
        self.rows.append({"id": case_id, "localStatus": status, "helperSpanStatus": "not-applicable",
                          "resultSha256": result_hash})

    def _pump(self, *, deadline: float) -> None:
        require(self.selector is not None, "H1 selector unavailable.")
        assert self.selector is not None
        remaining = deadline - time.monotonic()
        require(remaining > 0, "H1 I/O deadline exceeded.")
        for key, events in self.selector.select(min(.05, remaining)):
            if not events & selectors.EVENT_READ:
                continue
            name = key.data
            require(name in self.buffers, "Unknown H1 data endpoint.")
            try:
                raw = os.read(key.fd, 4097 - len(self.buffers[name]))
            except BlockingIOError:
                continue
            if not raw:
                if name in ("stdout", "stderr"):
                    self.pipe_eof.add(name)
                self.selector.unregister(key.fileobj)
                self.reads.discard(name)
                require(name != "suite" or b"\n" in self.buffers[name], "Suite EOF is failure, not continue.")
            else:
                self.buffers[name].extend(raw)
                require(len(self.buffers[name]) <= 4096, "H1 data/output overflow.")
                require(not (name == "actor" and self.actor_consumed)
                        and not (name == "suite" and self.suite_consumed), "Extra H1 control bytes after its sole frame.")

    def _receive(self, name: str, *, deadline: float) -> bytes:
        while b"\n" not in self.buffers[name]:
            require(name in self.reads, "H1 endpoint closed before complete frame.")
            self._pump(deadline=deadline)
        raw = bytes(self.buffers[name])
        require(raw.count(b"\n") == 1 and raw.endswith(b"\n"), "Extra/truncated H1 frame.")
        return raw

    def _spawn(self) -> None:
        self.session._check()
        self.ticket = self.session.prepare_helper("tests/identity_actor.py")
        parent, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        self.channel = parent
        try:
            for fd in (parent.fileno(), child.fileno()):
                os.set_inheritable(fd, False)
            require(3 <= child.fileno() <= 65535 and child.fileno() not in self.ticket.pass_fds,
                    "Control and admission descriptions overlap.")
            self.child = subprocess.Popen([*self.ticket.prefix, "lease-hold", "chatgpt", "H1-independent-lease",
                                           self.fixture.case, str(child.fileno())],
                env=self.ticket.environment(dict(os.environ)), pass_fds=(*self.ticket.pass_fds, child.fileno()),
                close_fds=True, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                cwd=self.session.registry.root)
            owner = process_identity(self.child.pid)
            require(matches(owner, parent=os.getpid()), "Real direct child identity unavailable.")
            self.child_owner = owner
            # No background worker: the real synchronous acknowledge body must
            # return/raise before ticket.close, so there is no unjoined ACK.
            self.ticket.acknowledge(self.child.pid)
            require(self.ticket.completed, "Actual H1 acknowledge did not complete.")
            self.ticket.close()
        finally:
            child.close()
        require(self.child.stdout is not None and self.child.stderr is not None, "Missing actual H1 pipes.")
        assert self.child.stdout is not None and self.child.stderr is not None
        self.selector = selectors.DefaultSelector()
        for name, stream in (("stdout", self.child.stdout), ("stderr", self.child.stderr), ("actor", parent)):
            os.set_blocking(stream.fileno(), False)
            self.selector.register(stream, selectors.EVENT_READ, name)
            self.reads.add(name)

    def _observe_short_lock_origins(self) -> tuple[bytes, bytes]:
        """Actual ready-return origins, not a future recapture or lock inode.

        These raw directory descriptions hold NO flock. Never open/create,
        delete, acquire or reclaim the ephemeral Subscription lock itself.
        """
        require(self.short_lock_origins is None, "Short-lock origins cannot be refreshed.")
        self.fixture.check()
        opened: list[PrivateDirectory] = []
        original: BaseException | None = None
        try:
            parent = PrivateDirectory(self.fixture.path)
            opened.append(parent)
            origins: list[tuple[str, int, int, int, int]] = []
            for name, relative in (("state", "state"), ("subscriptions", "state/subscriptions"),
                                   ("chatgpt", "state/subscriptions/chatgpt")):
                parent.check()
                current = PrivateDirectory(parent.path / name)
                opened.append(current)
                named = os.stat(name, dir_fd=parent.fd, follow_symlinks=False)
                info = current.info
                require((info.st_dev, info.st_ino) == (named.st_dev, named.st_ino)
                        and stat.S_ISDIR(named.st_mode) and info.st_uid == named.st_uid == os.getuid()
                        and stat.S_IMODE(info.st_mode) == stat.S_IMODE(named.st_mode) == 0o700,
                        "Original physical short-lock directory/parent relationship changed.")
                origins.append((relative, info.st_dev, info.st_ino, info.st_uid, stat.S_IMODE(info.st_mode)))
                parent.check()
                current.check()
                parent = current
            root_raw = opened[1].read("identity.json")
            sidecar_raw = opened[3].read("identity.json")
            require(root_raw is not None and sidecar_raw is not None, "Real H1 local proof is absent.")
            for directory in opened:
                directory.check()
            # Retain all THREE original identities before closing observers.
            # Later checks compare these values; they may never replace them.
            self.short_lock_origins = tuple(origins)
            assert root_raw is not None and sidecar_raw is not None
            return root_raw, sidecar_raw
        except BaseException as error:
            original = error
            raise
        finally:
            failures: list[BaseException] = []
            for directory in reversed(opened):
                try:
                    directory.__exit__(None, None, None)
                except BaseException as error:
                    failures.append(error)
            if failures:
                if original is not None:
                    for cleanup_error in failures:
                        original.add_note("Short-lock origin observer close: " + type(cleanup_error).__name__)
                else:
                    raise BaseExceptionGroup("Short-lock origin observer cleanup failed.", failures)

    def _recheck_short_lock_origins(self) -> None:
        require(self.short_lock_origins is not None, "No actual readiness directory origins exist.")
        assert self.short_lock_origins is not None
        self.fixture.check()
        for relative, device, inode, uid, mode in self.short_lock_origins:
            # relative is retained from the fixed literal three-element list;
            # no control/frame/evidence document can select an observer path.
            with PrivateDirectory(self.fixture.path / relative) as directory:
                info = directory.info
                require((info.st_dev, info.st_ino, info.st_uid, stat.S_IMODE(info.st_mode))
                        == (device, inode, uid, mode), "Original readiness directory was replaced or re-owned.")

    def run_h1(self) -> None:
        require(not self.h1_started and len(self.rows) == len(self.ordered) - 1
                and all(row["localStatus"] == "passed" for row in self.rows),
                "H1 cannot arm with failed/skipped/unavailable/pending/missing local work.")
        self.h1_started = True
        self.end = time.monotonic() + 60
        try:
            self._spawn()
            ready = self._receive("actor", deadline=min(self.end - 20, time.monotonic() + 10))
            value = document(ready)
            require(value == {"version": 1, "kind": "actor-ready", "case": self.fixture.case,
                              "action": "lease-hold", "window": "H1-independent-lease"}
                    and type(value["version"]) is int and canonical(value) == ready,
                    "Wrong actual H1 capture-return readiness.")
            self.actor_consumed = True
            ready_at = time.monotonic()
            self.fixture.publish("actor-ready.json", ready)
            assert self.ticket is not None and self.child_owner is not None
            with PrivateDirectory(self.ticket.context_path.parent) as directory:
                context_raw = directory.read(self.ticket.context_path.name)
            require(context_raw is not None, "Missing real H1 context.")
            assert context_raw is not None
            context = document(context_raw)
            require(self.ticket.pending["phase"] == "accepted"
                    and self.ticket.pending["contextSha256"] == sha(context_raw)
                    and context["invocation"] == self.session.context["invocation"]
                    and context["component"] == COMPONENT and context["epoch"] == self.session.context["epoch"]
                    and context["boot"] == self.session.context["boot"]
                    and context["payloadSha256"] == self.session.context["payloadSha256"]
                    and context["acceptanceSha256"] == self.session.context["acceptanceSha256"]
                    and context["parent"] == {"writer": self.session.context["writer"], **identity_record(self.session.context["process"])}
                    and context["process"] == self.child_owner and context["entry"] == "tests/identity_actor.py",
                    "Actual helper context differs from parent/entry/direct-child bindings.")
            # Independently observe actual local proof persistence while our
            # parent Session is still genuinely admitted. These are exact owned
            # fixture paths, not native/profile inputs or actor-trusted proofs.
            root_raw, sidecar_raw = self._observe_short_lock_origins()
            require(root_raw is not None and sidecar_raw is not None, "Actual H1 capture did not persist local proof.")
            assert root_raw is not None and sidecar_raw is not None
            token(document(root_raw)["generation"])
            token(document(sidecar_raw)["witness"])
            with self.session.registry.mutex():
                live_writer = self.session.registry.writer(context["invocation"], context["writer"])
                require(live_writer["phase"] == "active" and live_writer["contextSha256"] == sha(context_raw)
                        and matches(self.child_owner, parent=os.getpid()), "H1 already stopped writing/exited before readiness.")
            preconditions = canonical({"version": 1, "kind": "abr38-H1-local-preconditions", "case": self.fixture.case,
                "actorReadySha256": sha(ready), "helperContextSha256": sha(context_raw),
                "persistedRootSha256": sha(root_raw), "persistedSidecarSha256": sha(sidecar_raw),
                "shortLockDirectories": [{"relative": relative, "device": device, "inode": inode, "uid": uid, "mode": mode}
                                         for relative, device, inode, uid, mode in self.short_lock_origins or ()]})
            self.fixture.publish("h1-preconditions.json", preconditions)
            self.rows.append({"id": H1_ID, "localStatus": "h1-preconditions-done", "helperSpanStatus": "pending",
                              "resultSha256": sha(preconditions)})
            inventory_hash = sha(self.inventory_raw)
            base = {"version": 1, "kind": "abr38-inner-phase-only", "component": COMPONENT,
                "build": self.session.authority.producer.declaration.build,
                "payloadSha256": self.session.context["payloadSha256"], "invocation": self.session.context["invocation"],
                "writer": self.session.context["writer"], "contextSha256": self.session.context_hash,
                "selected": list(self.ordered), "pendingExternal": list(self.pending), "inventorySha256": inventory_hash}
            base_raw = canonical(base, limit=1024 * 1024)
            local_raw = canonical({"version": 1, "kind": "abr38-helper-span-local-results", "component": COMPONENT,
                "inventorySha256": inventory_hash, "selectedSha256": sha(canonical(list(self.ordered), limit=1024 * 1024)),
                "h1CaseId": H1_ID, "rows": self.rows}, limit=1024 * 1024)
            named = os.stat(self.session.registry.folder / "admission.lock", follow_symlinks=False)
            held = os.fstat(self.session.lease)
            require((held.st_dev, held.st_ino) == (named.st_dev, named.st_ino)
                    and held.st_uid == os.getuid() and stat.S_IMODE(held.st_mode) == 0o600,
                    "Original active Suite admission lock changed.")
            report_raw = canonical({"version": 1, "kind": "abr38-preterminal-helper-span", "case": self.fixture.case,
                "component": COMPONENT, "phaseReportSha256": sha(base_raw), "localResultsSha256": sha(local_raw),
                "inventorySha256": inventory_hash, "suite": {"invocation": self.session.context["invocation"],
                    "writer": self.session.context["writer"], "contextSha256": self.session.context_hash,
                    **identity_record(self.session.context["process"])},
                "helper": {"entry": "tests/identity_actor.py", "invocation": context["invocation"],
                    "writer": context["writer"], "handoff": context["handoff"], "contextSha256": sha(context_raw),
                    **self.child_owner}, "actorReadySha256": sha(ready),
                "admissionLock": {"device": held.st_dev, "inode": held.st_ino}, "pendingExternal": list(self.pending)},
                limit=16 * 1024)
            self._recheck_short_lock_origins()
            for name, raw in (("phase-report.json", base_raw), ("local-results.json", local_raw), ("helper-span.json", report_raw)):
                self.fixture.publish(name, raw, limit=16 * 1024 if name == "helper-span.json" else 1024 * 1024)
            self._recheck_short_lock_origins()
            latch = min(self.end - 20, ready_at + 8)
            self.console.ready(sha(report_raw), deadline=latch)
            assert self.selector is not None
            self.selector.register(self.console.control[0], selectors.EVENT_READ, "suite")
            self.reads.add("suite")
            reply = self._receive("suite", deadline=latch)
            parsed = document(reply)
            require(parsed == {"version": 1, "kind": "helper-span-control", "case": self.fixture.case, "command": "continue"}
                    and type(parsed["version"]) is int and canonical(parsed) == reply,
                    "Observer EOF/malformed/extra frame cannot authorize success.")
            self.suite_consumed = True  # Keep reading to reject any later extra input.
            assert self.channel is not None
            self.channel.settimeout(max(.001, latch - time.monotonic()))
            self.channel.sendall(canonical({"version": 1, "kind": "actor-control", "case": self.fixture.case,
                                           "command": "continue"}))
            self._finish_actor(context, context_raw)
            self.completed = True
        finally:
            error = sys.exception()
            failures = self._cleanup()
            if error is not None or failures:
                failures.extend(self.abort_before_session_finish())
                if error is not None:
                    error.add_note("Owned H1 failure cleanup: " + ",".join(failures))
                elif failures:
                    raise FixtureFailure("Owned H1 cleanup unresolved: " + ",".join(failures))

    def _finish_actor(self, context: Object, context_raw: bytes) -> None:
        assert self.child is not None
        deadline = min(self.end - 20, time.monotonic() + 20)
        while "stdout" in self.reads or "stderr" in self.reads:
            self._pump(deadline=deadline)
        status = self.child.wait(timeout=max(.001, deadline - time.monotonic()))
        self.session._check()
        raw = bytes(self.buffers["stdout"])
        result = document(raw)
        require(status == 0 and result == {"version": 1, "kind": "actor-result", "case": self.fixture.case,
            "action": "lease-hold", "outcome": "completed"} and type(result["version"]) is int and canonical(result) == raw,
            "Actual H1 direct-child wait/result failed.")
        with self.session.registry.mutex():
            current = self.session.registry.writer(context["invocation"], context["writer"])
            require(current == {"version": 1, "invocation": context["invocation"], "writer": context["writer"],
                "parent": self.session.context["writer"], "component": COMPONENT, "epoch": self.session.context["epoch"],
                "payloadSha256": self.session.context["payloadSha256"], "boot": self.session.context["boot"],
                **context["process"], "phase": "terminal", "contextSha256": sha(context_raw)},
                "Really reaped helper lacks its actual terminal/context record.")
        self.fixture.publish("actor.stdout", raw)
        self.fixture.publish("actor.stderr", bytes(self.buffers["stderr"]))
        self.fixture.publish("helper-completion.json", canonical({"version": 1, "kind": "abr38-H1-actual-completion",
            "case": self.fixture.case, "process": self.child_owner, "waitStatus": status,
            "actorResultSha256": sha(raw), "contextSha256": sha(context_raw), "terminalRecordSha256": sha(canonical(current)),
            "ackPath": "synchronous-acknowledge-returned-before-ticket-close"}))

    def _cleanup(self) -> list[str]:
        # One transaction, including repeated abort/context-finalizer calls.
        # In particular, a second caller cannot restart a fresh twenty seconds.
        if self.cleanup_finished:
            return list(self.cleanup_errors)
        self.cleanup_finished = True
        errors = self.cleanup_errors
        deadline = min(self.end, time.monotonic() + 20) if self.h1_started else time.monotonic() + 20
        if self.channel is not None:
            try:
                self.channel.close()  # EOF is failure, never an actor continue.
            except BaseException as error:
                errors.append("control:" + type(error).__name__)
        if self.ticket is not None:
            try:
                # The real synchronous ACK always releases its ticket in its
                # finally. A pre-ACK spawn failure may instead need the actual
                # public close (whose default mutex has no caller deadline).
                # It cannot fit our strict shared budget by assumption. Preserve
                # pending custody/activity instead; never privately end them.
                if self.ticket._closed:
                    self.ticket.close()
                else:
                    errors.append("ticket-close-unavailable-within-shared-budget:activity-and-custody-unresolved")
                    for endpoint in (self.ticket.child_socket, self.ticket.frames):
                        try:
                            endpoint.close()
                        except BaseException as error:
                            errors.append("ticket-endpoint:" + type(error).__name__)
            except BaseException as error:
                errors.append("ticket:" + type(error).__name__)
        if self.child is not None:
            try:
                if self.child.poll() is None:
                    if self.child_owner is not None and matches(self.child_owner, parent=os.getpid()):
                        os.kill(self.child.pid, signal.SIGCONT)
                        if matches(self.child_owner, parent=os.getpid()):
                            os.kill(self.child.pid, signal.SIGTERM)
                    else:
                        errors.append("live-child-ownership-unverified")
            except BaseException as error:
                errors.append("owned-stop:" + type(error).__name__)
            # Independently drain BOTH actual owned pipes, including failures
            # before the normal selector/ACK existed. Waiting first can deadlock
            # a full diagnostic pipe; closing first would discard its evidence.
            # Retain the first 4097 bytes (4096 + overflow witness), read at most
            # 128 KiB per pipe, and distinguish real EOF from every failure/cap.
            pending: dict[int, str] = {}
            drain: selectors.BaseSelector | None = None
            try:
                drain = selectors.DefaultSelector()
                for name, stream in (("stdout", self.child.stdout), ("stderr", self.child.stderr)):
                    self.failed_output[name] = {"alreadyObserved": len(self.buffers[name]), "cleanupRead": 0,
                                                "eofObserved": name in self.pipe_eof,
                                                "discardedAfterPrefix": 0}
                    if stream is None:
                        errors.append(name + ":missing-owned-pipe")
                        continue
                    try:
                        os.set_blocking(stream.fileno(), False)
                        drain.register(stream, selectors.EVENT_READ, name)
                        pending[stream.fileno()] = name
                    except BaseException as error:
                        errors.append(name + "-drain-setup:" + type(error).__name__)
                while pending and time.monotonic() < deadline:
                    for key, events in drain.select(min(.05, max(0, deadline - time.monotonic()))):
                        if not events & selectors.EVENT_READ:
                            continue
                        name = pending[key.fd]
                        facts = self.failed_output[name]
                        try:
                            raw = os.read(key.fd, min(8192, 128 * 1024 - facts["cleanupRead"]))
                        except BlockingIOError:
                            continue
                        except BaseException as error:
                            errors.append(name + "-drain-read:" + type(error).__name__)
                            drain.unregister(key.fileobj)
                            del pending[key.fd]
                            continue
                        if not raw:
                            facts["eofObserved"] = True
                            self.pipe_eof.add(name)
                            drain.unregister(key.fileobj)
                            del pending[key.fd]
                            continue
                        facts["cleanupRead"] += len(raw)
                        room = max(0, 4097 - len(self.buffers[name]))
                        self.buffers[name].extend(raw[:room])
                        facts["discardedAfterPrefix"] += max(0, len(raw) - room)
                        if len(self.buffers[name]) > 4096 and not facts.get("prefixOverflow"):
                            facts["prefixOverflow"] = True
                            errors.append(name + "-output-overflow:retained-prefix")
                        if facts["cleanupRead"] >= 128 * 1024:
                            errors.append(name + "-drain-byte-cap:unread-output-unresolved")
                            drain.unregister(key.fileobj)
                            del pending[key.fd]
                    # Poll only our actual Popen; never reap an adopted child.
                    self.child.poll()
                errors.extend(name + "-drain-deadline:unread-output-unresolved" for name in pending.values())
            except BaseException as error:
                errors.append("owned-output-drain:" + type(error).__name__)
            finally:
                if drain is not None:
                    try:
                        drain.close()
                    except BaseException as error:
                        errors.append("cleanup-selector:" + type(error).__name__)
            try:
                if self.child.poll() is None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        errors.append("owned-wait-deadline:process-unresolved")
                    else:
                        self.child.wait(timeout=remaining)
            except BaseException as error:
                errors.append("owned-wait:" + type(error).__name__)
            for stream in (self.child.stdout, self.child.stderr):
                if stream is not None:
                    try:
                        stream.close()
                    except BaseException as error:
                        errors.append("pipe:" + type(error).__name__)
        if self.selector is not None:
            try:
                self.selector.close()
            except BaseException as error:
                errors.append("selector:" + type(error).__name__)
        return list(errors)

    def abort_before_session_finish(self) -> list[str]:
        failures = self._cleanup()
        if not self.failure_preservation_attempted:
            self.failure_preservation_attempted = True
            try:
                self.fixture.preserve_failure(canonical({"version": 1, "kind": "abr38-failed-H1-evidence",
                    "case": self.fixture.case, "ordered": list(self.ordered), "rows": self.rows,
                    "pendingExternal": list(self.pending), "child": self.child_owner,
                    "childReturncode": None if self.child is None else self.child.returncode,
                    "actualOutputHex": {name: bytes(raw).hex() for name, raw in self.buffers.items()},
                    "failedOutputObservation": self.failed_output,
                    "cleanupErrors": failures, "terminalOrGatePassClaimed": False}, limit=4 * 1024 * 1024))
            except BaseException as error:
                failures.append("failed-evidence:" + type(error).__name__)
        try:
            self.console.close()
        except BaseException as error:
            failures.append("suite-control:" + type(error).__name__)
        return failures

    def close_before_session_finish(self) -> None:
        """Gate wrapper calls AFTER the real runner's final results/output."""
        require(self.completed, "Incomplete H1/local work cannot close as a passed check.")
        self.fixture.check()
        sys.stdout.flush()
        sys.stderr.flush()
        os.fsync(1)
        os.fsync(2)
        for name in ("runner.stdout", "runner.stderr"):
            self.fixture.read(name, limit=1024 * 1024)
        self.console.close()
        # stdio0/1/2 stay ordinary DEVNULL/private captures, never authority or
        # control grants. Caller must perform no application State/output after
        # this point; the REAL owning Session context alone finishes admission.


@dataclass(frozen=True)
class TerminalLocalResult:
    """Actual final local callback evidence, not a provisional4da status row.

    The fixed full-runner adapter creates these only after each actual unittest
    success, including the positive H1 case's AFTER-reap persistence assertions.
    The separate complete-body review must admit that exact callback/dataflow.
    No wire/environment can supply a result or shortened selection.
    """

    case_id: str
    actual_result: bytes


@dataclass(frozen=True)
class TerminalHelperWitness:
    """REAL source-owned ticket/Popen/result, never reported process claims."""

    ticket: HelperHandoff
    child: subprocess.Popen[bytes]
    owner: Identity
    actual_result: bytes


class CodexTerminalClose:
    """af1 fixed final own-close fixture; no manual finish or extra authority.

    The static runner nests EXACTLY as follows (not wired by this source):
        with CodexTerminalClose(real_session) as terminal:
            with real_session:
                with CodexH1Support(...) as support:
                    ... complete ALL real local/H1/tasks/output work ...
                    terminal.arm(support, ... actual final callback evidence ...)
    The owning Session context alone invokes finish. This OUTER fixture scope
    stays alive through that exit, restores only its own hook, and emits NOTHING
    after arm/finish. The full runner must catch propagated failures quietly and
    exit unsuccessfully; it must not add a traceback/application diagnostic.
    """

    def __init__(self, session: Session) -> None:
        self.session = session
        self.real_close = os.close
        self.hook = self._close
        self.close_code = Session._close_owned.__code__
        self.finish_code = Session.finish.__code__
        self.exit_code = Session.__exit__.__code__
        self.thread = threading.current_thread()
        self.thread_id = threading.get_ident()
        self.entered = False
        self.armed = False
        self.finish_may_have_begun = False
        self.matched = False
        self.real_close_called = False
        self.restored = False
        self.saved_fd = -1
        self.saved_identity: tuple[int, int, int, int] | None = None
        self.suite: Identity | None = None
        self.lock_path: Path | None = None
        self.unavailable: str | None = None

    def __enter__(self) -> CodexTerminalClose:
        require(not self.entered and not self.session._entered and self.session.lease >= 3
                and type(self.session) is Session and os.close is self.real_close
                and getattr(self.real_close, "__module__", None) == "posix"
                and getattr(self.real_close, "__name__", None) == "close",
                "Fixed terminal fixture must enclose the one REAL owning Session context.")
        self.entered = True
        return self

    def __exit__(self, kind: type[BaseException] | None, error: BaseException | None,
                 traceback: TracebackType | None) -> None:
        # NO State/metadata/stdio/evidence/diagnostic operation here. Actual
        # Session.__exit__ already ran; restoring the OS function is not a retry
        # of finish, terminal publication or an admission-description close.
        changed = os.close is not self.real_close and os.close is not self.hook
        if os.close is self.hook:
            os.close = self.real_close
        self.restored = not changed
        positive_exit = (error is None or (isinstance(error, SystemExit)
                         and (error.code is None or (type(error.code) is int and error.code == 0))))
        if not positive_exit:
            if error is not None and (changed or self.unavailable is not None):
                error.add_note("Fixed own-close fixture unavailable; original real API failure retained.")
            return
        # Real Session.__exit__ explicitly permits SystemExit. A successful
        # SystemExit(0) still owes every fixture observation; it cannot bypass
        # arm/actual own-close by being classified as an arbitrary exception.
        require(not changed and self.armed and self.matched and self.real_close_called
                and self.unavailable is None and not self.session._entered and self.session.lease < 0,
                "Real terminal/own-close fixture was not completed; no positive check.")

    def _sole_thread(self) -> bool:
        return (threading.current_thread() is self.thread and threading.get_ident() == self.thread_id
                and threading.enumerate() == [self.thread])

    def _original_fd(self, fd: int) -> bool:
        if type(fd) is not int or fd != self.saved_fd or self.saved_identity is None or self.lock_path is None:
            return False
        held, named = os.fstat(fd), self.lock_path.lstat()
        return (stat.S_ISREG(held.st_mode) and stat.S_ISREG(named.st_mode)
                and held.st_nlink == named.st_nlink == 1
                and (held.st_dev, held.st_ino, held.st_uid, stat.S_IMODE(held.st_mode)) == self.saved_identity
                and (named.st_dev, named.st_ino, named.st_uid, stat.S_IMODE(named.st_mode)) == self.saved_identity)

    def _site(self, frame: FrameType) -> bool:
        parent = frame.f_back
        owning_exit = None if parent is None else parent.f_back
        return (frame.f_code is self.close_code and frame.f_locals.get("self") is self.session
                and parent is not None and parent.f_code is self.finish_code
                and parent.f_locals.get("self") is self.session
                and owning_exit is not None and owning_exit.f_code is self.exit_code
                and owning_exit.f_locals.get("self") is self.session
                and Session.__exit__.__code__ is self.exit_code
                and Session._close_owned.__code__ is self.close_code and Session.finish.__code__ is self.finish_code)

    def _close(self, fd: int) -> None:
        if type(fd) is not int or fd != self.saved_fd:
            self.real_close(fd)  # All other resource closes retain real behavior.
            return
        # In-memory-only checks at the literal OS boundary. Do not call current_
        # session/_check: real Codex finish already set _closing/lease=-1.
        self.finish_may_have_begun = True
        try:
            exact = (not self.matched and self.armed and self._sole_thread()
                     and self._site(sys._getframe(1)) and self._original_fd(fd)
                     and self.suite is not None and self.suite["pid"] == os.getpid()
                     and self.session.lease == -1 and self.session._closing and matches(self.suite))
        except BaseException:
            self.unavailable = "original-fd-or-site-observation-failed"
            os.close = self.real_close
            self.real_close_called = True
            self.real_close(fd)
            raise
        if not exact:
            # The real nonmatching close still runs unchanged, WITHOUT STOP.
            # Its caller/API error remains original; outer scope refuses a pass.
            self.unavailable = "saved-fd-site-thread-or-birth-mismatch"
            os.close = self.real_close
            self.real_close_called = True
            self.real_close(fd)
            return
        self.matched = True
        stop_error: BaseException | None = None
        try:
            assert self.suite is not None
            os.kill(self.suite["pid"], signal.SIGSTOP)
        except BaseException as error:
            stop_error = error
            self.unavailable = "actual-self-stop-failed"
        finally:
            # On CONT (or failed STOP), restore BEFORE the ONE genuine close.
            # Never emit a postterminal message or read/write product State.
            os.close = self.real_close
            self.restored = True
            self.real_close_called = True
            self.real_close(fd)  # Original result/error, no retry or LOCK_UN.
        if stop_error is not None:
            raise stop_error

    def _helper_rows(self, support: CodexH1Support, witnesses: Sequence[TerminalHelperWitness],
                     expected_entries: Sequence[str]) -> list[Object]:
        require(len(witnesses) <= 4096 and len(witnesses) == len(expected_entries)
                and tuple(item.ticket.pending["handoff"] for item in witnesses) == tuple(self.session.handoffs),
                "Actual full helper schedule is missing/extra/reordered.")
        require(support.ticket is not None and support.child is not None and support.child_owner is not None
                and any(item.ticket is support.ticket and item.child is support.child for item in witnesses),
                "Actual positive H1 ticket/Popen is absent from terminal settlement.")
        rows: list[Object] = []
        for index, (item, expected_entry) in enumerate(zip(witnesses, expected_entries, strict=True)):
            ticket, child = item.ticket, item.child
            require(ticket.parent is self.session and ticket.completed and ticket._closed
                    and ticket.pending["phase"] == "accepted"
                    and ticket.pending["entry"] == expected_entry
                    and expected_entry in self.session.authority.producer.declaration.helpers
                    and type(child.pid) is int and child.pid == item.owner["pid"]
                    and type(child.returncode) is int and child.returncode == 0 and child.wait(timeout=0) == 0
                    and not matches(item.owner) and len(item.actual_result) <= 65536,
                    "Actual helper source/ACK/direct-child reap/result is incomplete.")
            with PrivateDirectory(ticket.context_path.parent) as directory:
                raw = directory.read(ticket.context_path.name)
            require(raw is not None, "Actual finished helper context is absent.")
            assert raw is not None
            context = document(raw)
            require(ticket.pending["contextSha256"] == sha(raw)
                    and context["process"] == item.owner and context["entry"] == expected_entry
                    and context["parent"] == {"writer": self.session.context["writer"],
                                              **identity_record(self.session.context["process"])}
                    and all(context[key] == self.session.context[key] for key in
                            ("invocation", "component", "epoch", "boot", "payloadSha256", "acceptanceSha256")),
                    "Actual terminal helper context/parent/tuple differs.")
            with self.session.registry.mutex():
                with PrivateDirectory(ticket.context_path.parent) as directory:
                    accepted_raw = directory.read(token(context["handoff"]) + ".json")
                require(accepted_raw is not None and document(accepted_raw) == ticket.pending,
                        "Actual accepted handoff differs from the source-owned completed ticket.")
                terminal = self.session.registry.writer(context["invocation"], context["writer"])
                expected = {"version": 1, "invocation": context["invocation"], "writer": context["writer"],
                    "parent": self.session.context["writer"], "component": COMPONENT, "epoch": context["epoch"],
                    "payloadSha256": context["payloadSha256"], "boot": context["boot"], **context["process"],
                    "phase": "terminal", "contextSha256": sha(raw)}
                require(terminal == expected and self.session.handoffs[context["handoff"]] == ticket.pending,
                        "Really reaped helper lacks its actual original terminal/accepted handoff.")
            if ticket is support.ticket:
                completion = document(support.fixture.read("helper-completion.json"))
                require(child is support.child and item.owner == support.child_owner
                        and item.actual_result == bytes(support.buffers["stdout"])
                        and completion["waitStatus"] == child.returncode
                        and completion["actorResultSha256"] == sha(item.actual_result)
                        and completion["contextSha256"] == sha(raw)
                        and completion["terminalRecordSha256"] == sha(canonical(terminal)),
                        "Actual positive H1 result/wait/terminal receipt differs from the terminal witness.")
            # These source-bound receipts bind actual returned synchronous ACK,
            # accepted context, real Popen wait and genuine terminal bytes. They
            # never grant authority or replace the outer independent graph.
            ack_raw = canonical({"version": 1, "kind": "abr38-terminal-helper-actual-ack", "handoff": ticket.pending,
                "contextSha256": sha(raw), "process": item.owner,
                "ackPath": "synchronous-acknowledge-returned-before-ticket-close"}, limit=16 * 1024)
            for name, evidence in ((f"terminal-helper-{index:04d}.context", raw),
                                   (f"terminal-helper-{index:04d}.terminal", canonical(terminal)),
                                   (f"terminal-helper-{index:04d}.result", item.actual_result),
                                   (f"terminal-helper-{index:04d}.ack", ack_raw)):
                support.fixture.publish(name, evidence, limit=65536)
            rows.append({"invocation": context["invocation"], "writer": context["writer"], "handoff": context["handoff"],
                "contextSha256": sha(raw), **item.owner, "waitStatus": child.returncode,
                "resultSha256": sha(item.actual_result), "terminalRecordSha256": sha(canonical(terminal)),
                "ackEvidenceSha256": sha(ack_raw)})
        return rows

    def arm(self, support: CodexH1Support, *, tuple_pins_sha256: str,
            completed_local_results: Sequence[TerminalLocalResult], finished_helpers: Sequence[TerminalHelperWitness],
            expected_helper_entries: Sequence[str]) -> None:
        require(self.entered and not self.armed and type(self.session) is Session
                and current_session() is self.session and support.session is self.session
                and support.completed and not support.console.closed and not support.cleanup_errors
                and len(completed_local_results) == len(support.ordered) <= 4096
                and re.fullmatch(r"[0-9a-f]{64}", tuple_pins_sha256, re.ASCII) is not None
                and self._sole_thread() and os.close is self.real_close,
                "Terminal arm requires the actual whole positive local/ACK/task/output completion.")
        self.session._check()
        with self.session._activity:
            require(self.session._spawning == 0 and not self.session._closing,
                    "An actual spawning/ACK worker still owns Session activity.")
        payload = self.session.authority.producer
        source = payload.regular_file("src/arbol_codex_driver/admission.py")
        require(Path(self.close_code.co_filename).resolve(strict=True) == source
                and Path(self.finish_code.co_filename).resolve(strict=True) == source
                and Path(self.exit_code.co_filename).resolve(strict=True) == source
                and Session.__exit__.__code__ is self.exit_code
                and Session._close_owned.__code__ is self.close_code and Session.finish.__code__ is self.finish_code,
                "Actual real finish/close code objects differ from verified packaged source.")
        rows: list[Object] = []
        for index, (result, expected_id) in enumerate(zip(completed_local_results, support.ordered, strict=True)):
            require(type(result) is TerminalLocalResult and result.case_id == expected_id
                    and 0 < len(result.actual_result) <= 65536, "Final local result is missing/extra/reordered.")
            support.fixture.publish(f"terminal-local-{index:04d}.result", result.actual_result, limit=65536)
            rows.append({"id": expected_id, "resultSha256": sha(result.actual_result)})
        helpers = self._helper_rows(support, finished_helpers, expected_helper_entries)
        base_raw = support.fixture.read("phase-report.json", limit=1024 * 1024)
        base = document(base_raw, limit=1024 * 1024)
        require(base["selected"] == list(support.ordered) and base["pendingExternal"] == list(support.pending)
                and base["inventorySha256"] == sha(support.inventory_raw), "Original full-local base changed.")
        settled = canonical({"version": 1, "kind": "abr38-terminal-close-settled", "component": COMPONENT,
            "inventorySha256": sha(support.inventory_raw),
            "selectedSha256": sha(canonical(list(support.ordered), limit=1024 * 1024)),
            "rows": rows, "helpers": helpers, "pendingExternal": list(support.pending)}, limit=1024 * 1024)
        support.fixture.publish("terminal-close-settled.json", settled, limit=1024 * 1024)
        self.saved_fd = self.session.lease  # BEFORE real Codex resets lease=-1.
        self.lock_path = self.session.registry.folder / "admission.lock"
        held = os.fstat(self.saved_fd)
        self.saved_identity = (held.st_dev, held.st_ino, held.st_uid, stat.S_IMODE(held.st_mode))
        require(self.saved_fd >= 3 and self._original_fd(self.saved_fd)
                and held.st_uid == os.getuid() and stat.S_IMODE(held.st_mode) == 0o600,
                "Saved actual own original admission descriptor is unavailable.")
        self.suite = identity_record(self.session.context["process"])
        parent = self.session.context["parent"]
        require(isinstance(parent, dict), "Actual Suite parent is absent.")
        assert isinstance(parent, dict)
        provider_owner = identity_record({"pid": parent["pid"], "startedAt": parent["startedAt"]})
        require(matches(self.suite, parent=provider_owner["pid"])
                and self.suite["pid"] == os.getpid(), "Actual owning Suite kernel identity changed.")
        intent = canonical({"version": 1, "kind": "abr38-terminal-close-intent", "case": support.fixture.case,
            "component": COMPONENT, "tuplePinsSha256": tuple_pins_sha256, "phaseReportSha256": sha(base_raw),
            "settledSha256": sha(settled), "suite": {"invocation": self.session.context["invocation"],
                "writer": self.session.context["writer"], "handoff": self.session.context["handoff"],
                "contextSha256": self.session.context_hash, **self.suite},
            "provider": provider_owner,
            "admissionLock": {"device": held.st_dev, "inode": held.st_ino},
            "ownLease": {"fd": self.saved_fd, "device": held.st_dev, "inode": held.st_ino},
            "closeSite": "codex-original-admission-close"}, limit=16 * 1024)
        support.fixture.publish("terminal-close-intent.json", intent, limit=16 * 1024)
        # Every application/State/output assertion is complete BEFORE arming.
        sys.stdout.flush()
        sys.stderr.flush()
        os.fsync(1)
        os.fsync(2)
        end = min(support.end, time.monotonic() + 5)
        raw = canonical({"version": 1, "kind": "terminal-close-armed", "case": support.fixture.case,
                         "intentSha256": sha(intent)})
        require(not support.console.closed and len(support.console.control) == 3,
                "Existing separated runner stdio is unavailable.")
        with selectors.DefaultSelector() as selector:
            selector.register(support.console.control[1], selectors.EVENT_WRITE)
            remaining = memoryview(raw)
            while remaining:
                require(time.monotonic() < end, "Terminal armed frame exceeded its finite publication bound.")
                if selector.select(min(.05, max(0, end - time.monotonic()))):
                    try:
                        count = os.write(support.console.control[1], remaining)
                    except BlockingIOError:
                        continue
                    require(count > 0, "Terminal armed stdio closed before complete frame.")
                    remaining = remaining[count:]
        # Do not close/duplicate the original SH. Data controls are joined/closed
        # here; the ordinary support finalizer will then close an empty list.
        support.console.close()
        require(self._original_fd(self.saved_fd) and self._sole_thread() and os.close is self.real_close,
                "Saved own descriptor/thread/OS function changed before installation.")
        self.armed = True
        os.close = self.hook


LocalRequest = Literal["identity", "list"]


@dataclass(frozen=True)
class LocalInvocation:
    process: asyncio.subprocess.Process
    owner: Identity


@dataclass(frozen=True)
class LocalCapture:
    exit: int
    stdout: bytes
    stderr: bytes
    owner: Identity


class CodexLocalSubject:
    """An owned local fixture and fresh ordinary candidate Driver invocations."""

    def __init__(self, *, guarded_settings: bool = False) -> None:
        session = current_session()
        session._check()
        require(session.context["entry"] == "scripts/check_build.py"
                and session.context["role"] == "helper" and session.authority.status == "candidate"
                and sys.argv[1:] == ["unit"]
                and Path(sys.argv[0]) == session.authority.producer.regular_file("scripts/check_build.py"),
                "Local proof cases require the actual complete candidate unit runner.")
        self.fixture = FixtureRoot(session, uuid.uuid4().hex)
        self.session = session
        self.state = self.fixture.path / "state"
        self.home = self.fixture.path / "home"
        self.native = self.home / ".codex"
        self.tools = self.fixture.path / "tools"
        self.settings = self.home / ".arbol" / "arbol-codex-driver.json"
        for directory in (self.home, self.native, self.tools, self.settings.parent):
            directory.mkdir(mode=0o700)
        self.vendor_marker = self.fixture.path / "vendor-invoked"
        self.fake_secret = "abr38-disposable-output-sentinel"
        self.auth = self.native / "auth.json"
        self._publish(self.auth, canonical({"fixtureValue": self.fake_secret}))
        self._publish(self.settings, b"{deliberately unreadable fixture settings\n" if guarded_settings else canonical({
            "toolPath": str(self.tools / "codex"),
        }))
        # The stand-in fails closed and writes only this private sentinel if the
        # ordinary proof/list path ever starts a vendor executable.
        tool = self.tools / "codex"
        self._publish(tool, b'#!/bin/sh\nprintf "called\\n" > "$ABR38_VENDOR_MARKER"\nexit 97\n')
        tool.chmod(0o700)
        self.environment = {"HOME": str(self.home), "CODEX_HOME": str(self.native),
                            "PATH": str(self.tools) + ":/usr/bin:/bin", "LC_ALL": "C", "TZ": "UTC",
                            "ABR38_VENDOR_MARKER": str(self.vendor_marker), "ARBOL_TEST_TIME_SCALE": "0.1"}
        self.original_inputs = self._inputs()

    @staticmethod
    def _publish(path: Path, raw: bytes) -> None:
        with PrivateDirectory(path.parent) as directory:
            require(path.name not in os.listdir(directory.fd), "Local fixture would overwrite a real input.")
            directory.publish(path.name, raw)

    @staticmethod
    def _read(path: Path) -> tuple[bytes, tuple[int, int, int]]:
        with PrivateDirectory(path.parent) as directory:
            raw = directory.read(path.name)
            require(raw is not None, "Missing local evidence file.")
            info = os.stat(path.name, dir_fd=directory.fd, follow_symlinks=False)
            require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and info.st_nlink == 1,
                    "Local evidence file changed type or owner.")
            assert raw is not None
            return raw, (info.st_dev, info.st_ino, stat.S_IMODE(info.st_mode))

    def _inputs(self) -> tuple[tuple[bytes, tuple[int, int, int]], ...]:
        require(not os.path.lexists(self.vendor_marker), "Ordinary local request started the vendor stand-in.")
        with PrivateDirectory(self.tools) as directory:
            descriptor = os.open("codex", os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory.fd)
            try:
                held = os.fstat(descriptor)
                named = os.stat("codex", dir_fd=directory.fd, follow_symlinks=False)
                physical = (held.st_dev, held.st_ino, stat.S_IMODE(held.st_mode))
                require(stat.S_ISREG(held.st_mode) and held.st_uid == os.getuid() and held.st_nlink == 1
                        and physical == (named.st_dev, named.st_ino, 0o700) and 0 < held.st_size <= 4096,
                        "The owned vendor observation executable changed.")
                raw = os.read(descriptor, 4097)
                require(len(raw) == held.st_size and os.fstat(descriptor).st_mtime_ns == held.st_mtime_ns,
                        "Vendor sentinel bytes changed while reading.")
            finally:
                os.close(descriptor)
        return self._read(self.auth), self._read(self.settings), (raw, physical)

    def check_inputs(self) -> None:
        self.fixture.check()
        require(self._inputs() == self.original_inputs, "Ordinary local request modified native or settings inputs.")
        with PrivateDirectory(self.native) as directory:
            require(os.listdir(directory.fd) == ["auth.json"], "Ordinary local request created native/profile state.")

    def prepare_legacy(self, marker: bytes, *, journal: bytes | None = None, root: bytes | None = None) -> None:
        """Initial private fixture bytes for legacy/interrupted-format readers."""
        self.fixture.check()
        self.state.mkdir(mode=0o700)
        self._publish(self.state / "format", marker)
        self._publish(self.state / "identity.guard", b"")
        if journal is not None:
            self._publish(self.state / "identity-upgrade.json", journal)
        if root is not None:
            self._publish(self.state / "identity.json", root)

    def state_image(self) -> Object:
        """Snapshot the fixed fixture tree without following unexpected entries."""
        paths: Object = {}
        for folder, directories, files in os.walk(self.state, followlinks=False):
            base = Path(folder)
            with PrivateDirectory(base) as directory:
                paths[base.relative_to(self.state).as_posix()] = [directory.info.st_dev, directory.info.st_ino]
            for name in directories:
                with PrivateDirectory(base / name):
                    pass
            for name in files:
                file = base / name
                raw, inode = self._read(file)
                paths[file.relative_to(self.state).as_posix()] = {"sha256": sha(raw), "physical": list(inode)}
            require(len(paths) <= 256, "Unexpected local fixture inventory size.")
        return paths

    async def spawn(self, request: LocalRequest, expected: tuple[str, str] | None = None) -> LocalInvocation:
        authority = self.session.authority
        provider = authority.provider
        declaration = provider.declaration
        if request == "list":
            require(expected is None, "List does not accept identity expectation.")
            tail = ["subscriptions", "list"]
        else:
            require(request == "identity", "Unexpected local Driver request.")
            tail = ["subscriptions", "identity", "chatgpt"]
            if expected is not None:
                tail.extend(("--expect", ".".join(token(value) for value in expected)))
        argv = [str(provider.regular_file(declaration.interpreter)), "-ISB", str(provider.regular_file(declaration.entry)),
                "--qualification-launch", str(authority.registry), COMPONENT, authority.producer.declaration.build,
                "driver", "--", "--state-dir", str(self.state), *tail]
        process = await asyncio.create_subprocess_exec(
            *argv, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            cwd=self.fixture.path, env=self.environment, close_fds=True, limit=8192,
        )
        owner = process_identity(process.pid)
        require(matches(owner, parent=os.getpid()), "The actual public provider is not our verified child.")
        return LocalInvocation(process, owner)

    async def collect(self, invocation: LocalInvocation, name: str) -> LocalCapture:
        process = invocation.process
        assert process.stdout is not None and process.stderr is not None

        async def drain(stream: asyncio.StreamReader) -> bytes:
            raw = bytearray()
            while block := await stream.read(4096):
                raw.extend(block)
                require(len(raw) <= 4096, "Public Driver stream exceeded its local observation bound.")
            return bytes(raw)

        async with asyncio.timeout(100), asyncio.TaskGroup() as tasks:
            stdout = tasks.create_task(drain(process.stdout))
            stderr = tasks.create_task(drain(process.stderr))
            waited = tasks.create_task(process.wait())
        capture = LocalCapture(waited.result(), stdout.result(), stderr.result(), invocation.owner)
        self.fixture.publish(name + ".json", canonical({
            "owner": dict(capture.owner), "reapedExit": capture.exit, "stdoutHex": capture.stdout.hex(),
            "stderrHex": capture.stderr.hex(),
        }, limit=32768), limit=32768)
        require(self.fake_secret.encode() not in capture.stdout + capture.stderr,
                "Private fixture contents escaped the public Driver output.")
        self._terminal(capture.owner)
        return capture

    async def stop(self, invocation: LocalInvocation) -> None:
        process = invocation.process
        if process.returncode is None and matches(invocation.owner, parent=os.getpid()):
            process.terminate()
        async with asyncio.timeout(20):
            await process.wait()

    def _terminal(self, owner: Identity) -> None:
        registry = self.session.registry
        with registry.mutex(), PrivateDirectory(registry.folder / "writers") as writers:
            names = os.listdir(writers.fd)
            require(len(names) <= 4096, "Local invocation writer inventory exceeded its bound.")
            roots = []
            for invocation in names:
                with PrivateDirectory(registry.folder / "writers" / token(invocation)) as group:
                    entries = os.listdir(group.fd)
                    require(len(entries) <= 4096, "Local invocation writer group exceeded its bound.")
                    for name in entries:
                        require(name.endswith(".json"), "Unexpected public writer metadata entry.")
                        writer = registry.writer(invocation, name.removesuffix(".json"))
                        if (writer["pid"], writer["startedAt"]) == (owner["pid"], owner["startedAt"]):
                            roots.append(writer)
            require(len(roots) == 1, "Public proof provider has no independent real root disposition.")
            root = roots[0]
            require(root["phase"] == "terminal" and root["parent"] is None and not matches(owner),
                    "Actual public provider has not finished.")
            with PrivateDirectory(registry.folder / "handoffs") as directory:
                main = []
                names = os.listdir(directory.fd)
                require(len(names) <= 4096, "Local handoff inventory exceeded its bound.")
                for name in names:
                    if name.endswith(".context.json"):
                        continue
                    raw = directory.read(name)
                    if raw is None:
                        continue
                    row = document(raw)
                    if row["invocation"] == root["invocation"] and row["role"] == "main":
                        main.append(row)
                require(len(main) == 1, "Public proof has no exact accepted MAIN transfer.")
                transfer = main[0]
                writer = registry.writer(root["invocation"], transfer["child"])
                require(transfer["phase"] == "accepted" and transfer["parent"] == root["writer"]
                        and transfer["entry"] == self.session.authority.producer.declaration.entry
                        and writer["phase"] == "terminal" and writer["parent"] == root["writer"]
                        and writer["contextSha256"] == transfer["contextSha256"]
                        and writer["epoch"] == root["epoch"] == self.session.context["epoch"]
                        and not matches(identity_record({"pid": writer["pid"], "startedAt": writer["startedAt"]})),
                        "Actual MAIN custody did not finish.")
                with PrivateDirectory(registry.folder / "writers" / token(root["invocation"])) as group:
                    expected = {token(root["writer"]) + ".json", token(writer["writer"]) + ".json"}
                    require(set(os.listdir(group.fd)) == expected,
                            "The local proof invocation left an unexpected writer.")

    async def request(self, request: LocalRequest, name: str, expected: tuple[str, str] | None = None) -> LocalCapture:
        self.check_inputs()
        invocation = await self.spawn(request, expected)
        try:
            result = await self.collect(invocation, name)
        finally:
            await self.stop(invocation)
        self.check_inputs()
        return result

    async def waiting_pair(self, invocations: Sequence[LocalInvocation]) -> list[Object]:
        """Both exact MAIN processes must have reached the held real short lock."""
        subscription = self.state / "subscriptions/chatgpt"
        path = subscription / "lock"
        initial = self._read(path)
        require(document(initial[0])["owner"]["pid"] == os.getpid(), "The test runner did not own the held lock.")
        deadline = time.monotonic() + 80
        while time.monotonic() < deadline:
            waiting: dict[int, Object] = {}
            with PrivateDirectory(subscription) as directory:
                for name in os.listdir(directory.fd):
                    if re.fullmatch(r"\.write-[0-9a-f-]{36}", name) is None:
                        continue
                    try:
                        raw = directory.read(name)
                        pid = document(raw).get("owner", {}).get("pid") if raw else None
                    except (FileNotFoundError, Failure, ValueError):
                        # A contender may have just created its temporary file.
                        # Only a complete, stable owner row can count.
                        continue
                    if type(pid) is not int or pid == os.getpid():
                        continue
                    current = inspect(pid)
                    if current is None:
                        continue
                    for call in invocations:
                        if current.parent == call.owner["pid"] and matches(call.owner, parent=os.getpid()):
                            waiting[current.parent] = {"main": dict(current.identity), "provider": dict(call.owner)}
            if len(waiting) == 2:
                require(self._read(path) == initial and not os.path.lexists(subscription / "identity.json"),
                        "Both contenders must reach the first capture queue before sidecar publication.")
                return [waiting[call.owner["pid"]] for call in invocations]
            require(all(call.process.returncode is None for call in invocations), "A contender exited before real overlap.")
            await asyncio.sleep(0.02)
        raise FixtureFailure("The two public MAINs were never both observed at the held lock.")
