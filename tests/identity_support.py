"""Prospective Codex H1/full-unit support. No import-time I/O, CLI or admission shortcut.

Call only from the fixed admitted whole runner after independent body admission.
Actual runner callbacks supply every local result; reports never mean gate success.
"""
from __future__ import annotations

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
import time
from collections.abc import Sequence
from pathlib import Path
from types import TracebackType
from typing import Any, Literal

from arbol_codex_driver.admission import HelperHandoff, Session, current_session
from arbol_codex_driver.identity_protocol import PrivateDirectory, token
from arbol_codex_driver.process_identity import Identity, identity_record, matches, process_identity

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
