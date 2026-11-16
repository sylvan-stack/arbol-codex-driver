"""Prospective local proof and final H1 cases; no gate or inventory wiring."""
from __future__ import annotations

import asyncio
import base64
import json
import os
import shlex
import stat
import sys
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from identity_support import (
    H1_ID,
    CodexH1Support,
    CodexLocalSubject,
    LocalCapture,
    LocalInvocation,
    Object,
    canonical,
    document,
    require,
    sha,
)

from arbol_codex_driver.admission import current_session
from arbol_codex_driver.continuity import Chats, message_digest
from arbol_codex_driver.errors import Failure
from arbol_codex_driver.identity import LifetimeSnapshot
from arbol_codex_driver.identity_protocol import PrivateDirectory, canonical_bytes, object_fields, parse_bytes, token
from arbol_codex_driver.run_request import RunRequest
from arbol_codex_driver.runs import Runs
from arbol_codex_driver.state import State, owner_json, process_owner
from arbol_codex_driver.subscriptions import Subscriptions


@dataclass(frozen=True)
class H1CaseBinding:
    """One source-owned full-runner binding, never a control-data selector."""

    support: CodexH1Support


class HelperSpanTests(unittest.TestCase):
    _binding: ClassVar[H1CaseBinding | None] = None

    @classmethod
    def bind(cls, binding: H1CaseBinding) -> None:
        require(cls._binding is None and binding.support.session is current_session()
                and not binding.support.h1_started, "Repeated/foreign/inactive full-runner H1 binding.")
        binding.support.fixture.check()
        cls._binding = binding

    def test_helper_independent_lease(self) -> None:
        binding = self._binding
        if binding is None:
            self.fail("H1 requires its real admitted complete-runner binding; no standalone/subset pass.")
        assert binding is not None
        support = binding.support
        fixture = support.fixture
        fixture.check()
        self.assertEqual(support.ordered[-1], H1_ID)
        self.assertEqual(len(support.rows), len(support.ordered) - 1)
        for case_id, row in zip(support.ordered[:-1], support.rows, strict=True):
            self.assertEqual(row["id"], case_id)
            self.assertEqual((row["localStatus"], row["helperSpanStatus"]), ("passed", "not-applicable"))
            receipt_raw = fixture.read("result-" + row["resultSha256"] + ".json", limit=1024 * 1024)
            self.assertEqual(sha(receipt_raw), row["resultSha256"])
            receipt = document(receipt_raw, limit=1024 * 1024)
            self.assertEqual(set(receipt), {"version", "kind", "id", "status", "resultHex"})
            self.assertEqual((receipt["kind"], receipt["id"], receipt["status"]),
                             ("abr38-actual-local-result", case_id, "passed"))
        with PrivateDirectory(fixture.path) as directory:
            self.assertNotIn("state", os.listdir(directory.fd), "H1 needs a new owned local State.")
            os.mkdir("vendor", 0o700, dir_fd=directory.fd)
            os.fsync(directory.fd)
        # This parent is ACTUALLY admitted. Prepare canonical implicit chatgpt
        # through the real local identity API, never native login/auth/discovery.
        state = State(fixture.path / "state")
        original: BaseException | None = None
        try:
            state.initialize()
            subscriptions = Subscriptions(state, {}, [], fixture.path / "vendor/settings.json", {})
            initial = asyncio.run(subscriptions.identity("chatgpt"))
        except BaseException as error:
            original = error
            raise
        finally:
            try:
                state.close()
            except BaseException as cleanup:
                if original is None:
                    raise
                original.add_note("H1 preparation State close: " + type(cleanup).__name__)
        initial = object_fields(initial, {"version", "driver", "subscription", "generation", "witness"})
        self.assertEqual((initial["version"], initial["driver"], initial["subscription"]), (1, "codex", "chatgpt"))
        token(initial["generation"])
        token(initial["witness"])
        before = self._images(binding)
        self.assertEqual(before["format"], b"2\n")
        root = object_fields(parse_bytes(before["root"]), {"version", "generation"})
        sidecar = object_fields(parse_bytes(before["sidecar"]), {"version", "state", "witness"})
        self.assertEqual((root["generation"], sidecar["witness"]), (initial["generation"], initial["witness"]))
        self.assertEqual(sidecar["state"], "active")
        # Support retains real H1 inside this still-running local method while
        # reporting ONLY h1-preconditions-done/span-pending. Death subjects never
        # claim this method returned or that the complete check passed.
        support.run_h1()
        self.assertTrue(support.completed)
        self.assertIsNotNone(support.child)
        assert support.child is not None
        self.assertEqual(support.child.returncode, 0)
        self.assertEqual(self._images(binding), before)
        captured = object_fields(parse_bytes(fixture.read("h1-capture.json")),
                                 {"version", "driver", "subscription", "generation", "witness"})
        self.assertEqual(captured, initial)
        self.assertEqual(fixture.read("h1-capture.json"), canonical_bytes(initial))
        self.assertEqual((support.rows[-1]["id"], support.rows[-1]["localStatus"], support.rows[-1]["helperSpanStatus"]),
                         (H1_ID, "h1-preconditions-done", "pending"))
        support.session._check()  # The WHOLE Suite still owns its real lifetime.
        # The later real runner records actual success/failure after teardown;
        # it NEVER rewrites the immutable provisional report as full success.

    @staticmethod
    def _images(binding: H1CaseBinding) -> dict[str, bytes]:
        fixture = binding.support.fixture
        fixture.check()
        with PrivateDirectory(fixture.path / "state") as root:
            root_info = root.info
            with PrivateDirectory(fixture.path / "state/subscriptions") as subscriptions, PrivateDirectory(
                fixture.path / "state/subscriptions/chatgpt"
            ) as subscription:
                subscriptions_info, side_info = subscriptions.info, subscription.info
                root_raw, format_raw = root.read("identity.json"), root.read("format")
                side_raw = subscription.read("identity.json")
                require(root_raw is not None and format_raw is not None and side_raw is not None,
                        "Missing actual local proof bytes.")
                guard = os.stat("identity.guard", dir_fd=root.fd, follow_symlinks=False)
                require(stat.S_ISREG(guard.st_mode) and guard.st_uid == os.getuid()
                        and stat.S_IMODE(guard.st_mode) == 0o600 and guard.st_nlink == 1,
                        "Unsafe original local guard.")
                assert root_raw is not None and format_raw is not None and side_raw is not None
                return {"root": root_raw, "sidecar": side_raw, "format": format_raw,
                        "physical": canonical_bytes({"state": [root_info.st_dev, root_info.st_ino],
                            "subscriptions": [subscriptions_info.st_dev, subscriptions_info.st_ino,
                                              subscriptions_info.st_uid, stat.S_IMODE(subscriptions_info.st_mode)],
                            "subscription": [side_info.st_dev, side_info.st_ino],
                            "guard": [guard.st_dev, guard.st_ino, guard.st_uid, stat.S_IMODE(guard.st_mode)]})}


class LocalIdentityTests(unittest.TestCase):
    def test_signed_out_first_capture_contends_and_restart_accepts_persisted_proof(self) -> None:
        subject = CodexLocalSubject(guarded_settings=True)
        asyncio.run(self._contended_capture(subject))

    async def _contended_capture(self, subject: CodexLocalSubject) -> None:
        state = State(subject.state)
        subscription = subject.state / "subscriptions/chatgpt"
        sidecar = subscription / "identity.json"
        record = subscription / "record.json"
        invocations: list[LocalInvocation] = []

        async def hold_first_write() -> list[Object]:
            # The runner holds only its real short Subscription lock here.
            # Both separate public providers bring their own component/session
            # authority. The observer does not take the component mutex here.
            for _ in range(2):
                invocations.append(await subject.spawn("identity"))
            observations = await subject.waiting_pair(invocations)
            self.assertEqual(len({row["main"]["pid"] for row in observations}), 2)
            return observations

        try:
            try:
                state.initialize()
                self.assertFalse(os.path.lexists(sidecar) or os.path.lexists(record))
                root = subject._read(subject.state / "identity.json")
                guard = subject._read(subject.state / "identity.guard")
                observations = await state.with_subscription_lock("chatgpt", hold_first_write, subject.environment)
            finally:
                state.close()
            subject.fixture.publish("observed-lock-contention.json", canonical({"waiting": observations}))
            async with asyncio.TaskGroup() as tasks:
                captures = [tasks.create_task(subject.collect(call, f"first-proof-{index}"))
                            for index, call in enumerate(invocations, 1)]
        finally:
            async with asyncio.TaskGroup() as cleanup:
                for call in invocations:
                    cleanup.create_task(subject.stop(call))

        proof, simultaneous = (self._proof(task.result()) for task in captures)
        self.assertEqual(proof, simultaneous)
        self.assertEqual(subject._read(subject.state / "identity.json"), root)
        self.assertEqual(subject._read(subject.state / "identity.guard"), guard)
        self.assertEqual(document(root[0]), {"version": 1, "generation": proof["generation"]})
        persisted = subject._read(sidecar)
        self.assertEqual(persisted[0], canonical({"version": 1, "state": "active", "witness": proof["witness"]}))
        self.assertFalse(os.path.lexists(record), "Proof must preserve implicit signed-out chatgpt.")
        self.assertEqual(sorted(path.name for path in subscription.iterdir()), ["identity.json"])
        generation, witness = str(proof["generation"]), str(proof["witness"])
        restarted = await subject.request("identity", "restarted-exact-expect", (generation, witness))
        self.assertNotIn(restarted.owner, [call.owner for call in invocations])
        self.assertEqual(self._proof(restarted), proof)
        self.assertEqual(subject._read(sidecar), persisted)
        self.assertEqual(subject._read(subject.state / "identity.guard"), guard)
        subject.check_inputs()

    def test_qualified_list_preserves_format1_and_identity_requires_upgrade(self) -> None:
        subject = CodexLocalSubject()
        subject.prepare_legacy(b"1\n")
        asyncio.run(self._legacy_list(subject))

    async def _legacy_list(self, subject: CodexLocalSubject) -> None:
        before = subject.state_image()
        listed = await subject.request("list", "legacy-catalogue")
        self.assertEqual((listed.exit, listed.stderr), (0, b""))
        rows = json.loads(listed.stdout)
        self.assertIsInstance(rows, list)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(set(row), {"id", "family", "label", "auth", "state", "createdAt", "updatedAt", "settings"})
        self.assertEqual((row["id"], row["family"], row["auth"], row["state"]),
                         ("chatgpt", "chatgpt", "vendor_login", "signed_out"))
        self.assertEqual(subject.state_image(), before)
        refusal = await subject.request("identity", "legacy-proof-refusal")
        failure = self._failure(refusal, "invalid_input")
        self.assertEqual(failure["remedy"], "Upgrade Driver state under exclusive maintenance before using Subscription identity.")
        self.assertEqual(subject.state_image(), before)

    def test_interrupted_conversion_rejects_proof_and_list_without_repair(self) -> None:
        for phase in ("before-format", "after-root"):
            with self.subTest(phase=phase):
                subject = CodexLocalSubject()
                generation = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode("ascii")
                backup = subject.fixture.path / "historical-backup"
                backup.mkdir(mode=0o700)
                archive_rows = [{"path": "format", "present": True, "size": 2, "sha256": sha(b"1\n")}]
                for name in ("identity-maintenance.json", "identity-upgrade.json", "identity.json"):
                    archive_rows.append({"path": name, "present": False, "size": 0, "sha256": None})
                before_manifest = canonical({"version": 1, "kind": "driver-identity-backup", "format": 1,
                                             "files": archive_rows})
                subject._publish(backup / "manifest.json", before_manifest)
                subject._publish(backup / "format", b"1\n")
                journal = canonical_bytes({"version": 1, "from": 1, "to": 2, "generation": generation,
                                           "backup": str(backup), "backupSha256": sha(before_manifest)})
                # These are fixed initial reader inputs. An actual interrupted
                # maintenance operation and its retry need separate evidence.
                late = phase == "after-root"
                subject.prepare_legacy(b"2\n" if late else b"1\n", journal=journal,
                                       root=canonical_bytes({"version": 1, "generation": generation}) if late else None)
                asyncio.run(self._interrupted_refusals(subject, backup))

    async def _interrupted_refusals(self, subject: CodexLocalSubject, backup: Path) -> None:
        before = subject.state_image()
        archive = (subject._read(backup / "manifest.json"), subject._read(backup / "format"))
        for operation in ("identity", "list"):
            capture = await subject.request(operation, "interrupted-" + operation + "-refusal")
            self._failure(capture, "internal")
            self.assertEqual(subject.state_image(), before)
            self.assertEqual((subject._read(backup / "manifest.json"), subject._read(backup / "format")), archive)

    def _proof(self, capture: LocalCapture) -> dict[str, object]:
        self.assertEqual((capture.exit, capture.stderr), (0, b""))
        proof = document(capture.stdout)
        self.assertEqual(set(proof), {"version", "driver", "subscription", "generation", "witness"})
        self.assertIs(type(proof["version"]), int)
        self.assertEqual((proof["version"], proof["driver"], proof["subscription"]), (1, "codex", "chatgpt"))
        for field in ("generation", "witness"):
            value = proof[field]
            self.assertIsInstance(value, str)
            self.assertRegex(value, r"\A[A-Za-z0-9_-]{43}\Z")
            raw = base64.b64decode(value + "=", altchars=b"-_", validate=True)
            self.assertEqual(len(raw), 32)
            self.assertEqual(base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii"), value)
        return proof

    def _failure(self, capture: LocalCapture, code: str) -> dict[str, object]:
        self.assertEqual((capture.exit, capture.stderr), (1, b""))
        result = document(capture.stdout)
        self.assertEqual(set(result), {"error"})
        error = result["error"]
        self.assertIsInstance(error, dict)
        self.assertEqual(error["code"], code)
        return dict(error)


# The production app-server client must reach this real pipe reply after
# observing the original lifetime. The fixture never reads or writes State.
DELAYED_ACCOUNT_PEER = """\
import json
import os
import sys
import time
from pathlib import Path

folder = Path(sys.argv[1])
os.umask(0o077)
if sys.argv[2:] == ["--version"]:
    print("codex-cli 0.162.1")
    sys.exit(0)
if sys.argv[2] != "app-server":
    sys.exit(2)
for line in sys.stdin:
    request = json.loads(line)
    method = request["method"]
    if method == "initialized":
        continue
    if method == "initialize":
        result = {"codexHome": os.environ["CODEX_HOME"], "userAgent": "codex/0.162.1"}
    elif method == "config/read":
        result = {"config": {"check_for_update_on_startup": False, "web_search": "live",
                             "analytics": {"enabled": False}, "features": {"memories": False}}}
    elif method in ("account/read", "account/rateLimits/read"):
        record = folder / "request.tmp"
        record.write_text(json.dumps({"method": method, "pid": os.getpid()}))
        record.replace(folder / "request.json")
        deadline = time.monotonic() + 20
        while not (folder / "release").exists():
            if time.monotonic() >= deadline:
                sys.exit(3)
            time.sleep(0.01)
        if method == "account/read":
            result = {"account": {"type": "chatgpt", "email": "old@example.invalid", "planType": "fixture"}}
        else:
            result = {"rateLimits": {"primary": {"usedPercent": 73, "windowDurationMins": 300}}}
        (folder / "reply-ready").touch(exist_ok=False)
        print(json.dumps({"id": request["id"], "result": result}), flush=True)
        continue
    else:
        sys.exit(4)
    print(json.dumps({"id": request["id"], "result": result}), flush=True)
"""


class LifetimeRaceTests(unittest.TestCase):
    subscription_id = "historical-chatgpt"
    timestamp = "2026-01-01T00:00:00.000Z"

    def test_fresh_list_reaps_a_dead_predecessor_receipt_without_adopting_its_verdict(self) -> None:
        asyncio.run(self._reap_predecessor())

    def test_delayed_account_check_and_usage_preserve_successor_of_same_identifier(self) -> None:
        for method in ("account/read", "account/rateLimits/read"):
            with self.subTest(method=method):
                asyncio.run(self._delayed_account_reply(method))

    def test_late_run_settlement_cannot_recreate_a_map_or_remove_successor_reservation(self) -> None:
        asyncio.run(self._late_run_settlement())

    def test_failed_run_cannot_remove_a_newer_map_revision_for_the_same_conversation(self) -> None:
        asyncio.run(self._late_map_cleanup())

    def _subscriptions(self, subject: CodexLocalSubject, state: State, tool: Path | None = None) -> Subscriptions:
        return Subscriptions(state, {} if tool is None else {"toolPath": str(tool)}, [],
                             subject.settings, subject.environment)

    def _record(self, folder: Path, label: str) -> None:
        # Codex has no command to create a second native account. A fixture
        # record represents a historical isolated Subscription, and after
        # ordinary removal the same selector receives another fixture record.
        # The real identity path, never fixture data, supplies both proofs.
        CodexLocalSubject._publish(folder / "record.json", canonical({
            "id": self.subscription_id, "family": "chatgpt", "auth": "vendor_login",
            "label": label, "state": "signed_in", "createdAt": self.timestamp,
            "updatedAt": self.timestamp, "checkedAt": self.timestamp,
            "account": {"email": "kept@example.invalid", "plan": "fixture"},
        }))

    async def _retire_and_replace(
        self, subscriptions: Subscriptions, folder: Path, original: Object,
    ) -> Object:
        identifier = self.subscription_id
        await subscriptions.remove(identifier)
        self.assertFalse(os.path.lexists(folder / "record.json"))
        self.assertFalse(os.path.lexists(folder / "identity-pending.json"))
        retired, _ = CodexLocalSubject._read(folder / "identity.json")
        self.assertEqual(document(retired), {"version": 1, "state": "retired", "witness": original["witness"]})
        self._record(folder, "Successor")
        successor = await subscriptions.identity(identifier)
        self.assertEqual(successor["generation"], original["generation"])
        self.assertNotEqual(successor["witness"], original["witness"])
        return successor

    async def _reap_predecessor(self) -> None:
        subject = CodexLocalSubject()
        state = State(subject.state)
        identifier = self.subscription_id
        state.initialize()
        try:
            subscriptions = self._subscriptions(subject, state)
            folder = state.subscription(identifier)
            folder.mkdir(parents=True, mode=0o700)
            self._record(folder, "Original")
            proof = await subscriptions.identity(identifier)
            child = await asyncio.create_subprocess_exec(
                "/bin/cat", stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            )
            try:
                owner = await process_owner(child.pid)
            finally:
                assert child.stdin is not None
                child.stdin.close()
                try:
                    await asyncio.wait_for(child.wait(), 5)
                except TimeoutError:
                    if child.returncode is None:
                        child.kill()
                    await child.wait()
                    raise
            assert owner is not None
            self.assertEqual(child.returncode, 0)
            self.assertIsNone(await process_owner(child.pid))
            successor = await self._retire_and_replace(subscriptions, folder, proof)

            stale: Object = {"owner": owner_json(owner), "attempt": "dead-predecessor", "operation": "sign_in",
                             "expiresAt": self.timestamp, "byCode": False,
                             "lifetime": {key: proof[key] for key in ("subscription", "generation", "witness")}}
            progress = folder / "sign-in.json"
            subject._publish(progress, canonical(stale))
            # Prime only the unrelated implicit catalogue entry, so its
            # short-lock directory creation cannot change the recovery image.
            await subscriptions.identity("chatgpt")
            before = subject.state_image()
            del before[progress.relative_to(subject.state).as_posix()]
            listed = await subject.request("list", "reap-dead-predecessor")
            self.assertEqual((listed.exit, listed.stderr), (0, b""))
            rows = json.loads(listed.stdout)
            self.assertEqual([(row["id"], row["state"]) for row in rows],
                             [("chatgpt", "signed_out"), (identifier, "signed_in")])
            self.assertFalse(os.path.lexists(progress))
            self.assertEqual(subject.state_image(), before)

            current = await subscriptions.reserve(identifier, "sign_out")
            try:
                before = subject.state_image()
                with self.assertRaises(Failure) as rejected:
                    await subscriptions.finish(identifier, stale, {"state": "signed_in"})
                self.assertEqual(rejected.exception.result["code"], "in_use")
                self.assertEqual(subject.state_image(), before)
                self.assertEqual(await subscriptions.identity(identifier), successor)
            finally:
                await subscriptions.finish(identifier, current)
            self.assertFalse(os.path.lexists(progress))
            subject.check_inputs()
        finally:
            state.close()

    async def _delayed_account_reply(self, method: str) -> None:
        subject = CodexLocalSubject()
        state = State(subject.state)
        identifier = self.subscription_id
        fixture = subject.fixture.path
        script, tool = fixture / "peer.py", fixture / "peer-codex"
        subject._publish(script, DELAYED_ACCOUNT_PEER.encode())
        command = shlex.join((sys.executable, "-ISB", str(script), str(fixture)))
        subject._publish(tool, f"#!/bin/sh\nexec {command} \"$@\"\n".encode())
        tool.chmod(0o700)
        state.initialize()
        try:
            subscriptions = self._subscriptions(subject, state, tool)
            folder = state.subscription(identifier)
            folder.mkdir(parents=True, mode=0o700)
            self._record(folder, "Original")
            proof = await subscriptions.identity(identifier)
            check = method == "account/read"
            async with asyncio.TaskGroup() as group:
                pending = group.create_task(self._observe_delayed_result(subscriptions, check=check))
                async with asyncio.timeout(15):
                    observed = fixture / "request.json"
                    while not observed.exists():
                        self.assertFalse(pending.done(), "Codex returned before the app-server reply.")
                        await asyncio.sleep(0.01)
                    request, _ = subject._read(observed)
                    row = document(request)
                    self.assertEqual(row["method"], method)
                    self.assertIs(type(row["pid"]), int)
                    owner = await process_owner(row["pid"])
                    self.assertIsNotNone(owner)
                    self.assertFalse(pending.done())
                    self.assertFalse(os.path.lexists(folder / "lock"), "Vendor reply wait holds the short lock.")
                    successor = await self._retire_and_replace(subscriptions, folder, proof)
                    preserved = subject.state_image()
                    self.assertFalse(pending.done())
                    subject._publish(fixture / "release", b"")
            verdict = pending.result()
            self.assertEqual(verdict["code"] if check else verdict["outcome"], "in_use" if check else "unavailable")
            self.assertIn("lifetime changed", verdict["message"])
            if not check:
                self.assertEqual(verdict["windows"], [])
            self.assertTrue((fixture / "reply-ready").is_file())
            self.assertIsNone(await process_owner(row["pid"]), "The original vendor process was not reaped.")
            self.assertEqual(subject.state_image(), preserved)
            self.assertEqual(await subscriptions.identity(identifier), successor)
            subject.check_inputs()
        finally:
            state.close()

    async def _observe_delayed_result(self, subscriptions: Subscriptions, *, check: bool) -> Object:
        if not check:
            return await subscriptions.usage(self.subscription_id)
        with self.assertRaises(Failure) as rejected:
            await subscriptions.check(self.subscription_id)
        return rejected.exception.result

    @staticmethod
    def _lifetime(proof: Object) -> LifetimeSnapshot:
        return LifetimeSnapshot.parse({key: proof[key] for key in ("subscription", "generation", "witness")})

    async def _late_run_settlement(self) -> None:
        subject = CodexLocalSubject()
        identifier = self.subscription_id
        state = State(subject.state)
        state.initialize()
        try:
            subscriptions = self._subscriptions(subject, state)
            folder = state.subscription(identifier)
            folder.mkdir(parents=True, mode=0o700)
            self._record(folder, "Original")
            proof = await subscriptions.identity(identifier)
            old_lifetime = self._lifetime(proof)
            request = RunRequest("reused-run", identifier, [], {}, "none",
                                 working_directory=str(subject.fixture.path), chat_session_id="fixture-chat")
            chats = Chats(state)
            runs = Runs(state, subject.environment)
            map_path = chats.path(identifier, sha(b"fixture-chat"))

            async def begin() -> tuple[Object, Object]:
                reservation = await runs.reserve(request.run_id, identifier, lifetime=old_lifetime)
                return reservation, await chats.select(request, lifetime=old_lifetime)

            reservation, plan = await state.with_subscription_lock(identifier, begin, subject.environment)
            self.assertIsNone(plan["initialMap"])

            # Exercise the actual settlement callbacks with inputs captured
            # before retirement. The local latch supplies scheduling only.
            release = asyncio.Event()

            async def settle_original() -> None:
                await release.wait()
                await subscriptions.store_run_usage(
                    old_record, {"outcome": "ok", "fetchedAt": "2099-01-01T00:00:00Z", "windows": []},
                    lifetime=old_lifetime,
                )
                await chats.settle(request, plan, "old-conversation", message_digest([]), True,
                                   lifetime=old_lifetime)
                await runs.finish(reservation)

            old_record = subscriptions.record(identifier)
            async with asyncio.TaskGroup() as group:
                old = group.create_task(settle_original())
                await runs.finish(reservation)
                self.assertFalse(os.path.lexists(runs.path(request.run_id)))
                successor = await self._retire_and_replace(subscriptions, folder, proof)

                async def begin_successor() -> Object:
                    return await runs.reserve(request.run_id, identifier, lifetime=self._lifetime(successor))

                current = await state.with_subscription_lock(identifier, begin_successor, subject.environment)
                self.assertEqual(current["owner"], reservation["owner"])
                self.assertNotEqual(current["lifetime"], reservation["lifetime"])
                self.assertFalse(os.path.lexists(map_path))
                before = subject.state_image()
                self.assertFalse(old.done())
                release.set()

            self.assertFalse(os.path.lexists(map_path), "An older lifetime re-created the removed chat map.")
            self.assertEqual(subject.state_image(), before)
            self.assertEqual(await subscriptions.identity(identifier), successor)
            await runs.finish(current)
            self.assertFalse(os.path.lexists(runs.path(request.run_id)))
            subject.check_inputs()
        finally:
            state.close()

    async def _late_map_cleanup(self) -> None:
        subject = CodexLocalSubject()
        identifier = self.subscription_id
        state = State(subject.state)
        state.initialize()
        try:
            subscriptions = self._subscriptions(subject, state)
            folder = state.subscription(identifier)
            folder.mkdir(parents=True, mode=0o700)
            self._record(folder, "Current")
            proof = await subscriptions.identity(identifier)
            lifetime = self._lifetime(proof)
            request = RunRequest("map-revision", identifier, [], {}, "none",
                                 working_directory=str(subject.fixture.path), chat_session_id="fixture-chat")
            chats = Chats(state)
            path = chats.path(identifier, sha(b"fixture-chat"))
            fingerprint = message_digest([])
            initial: Object = {"initialMap": None}
            await chats.settle(request, initial, "same-conversation", fingerprint, True, lifetime=lifetime)
            first = chats.entry(identifier, path.stem)
            assert first is not None
            previous: Object = {"continuedConversation": "same-conversation", "continuedMapRevision": first["revision"]}
            await chats.settle(request, {"initialMap": first}, "same-conversation", fingerprint, True, lifetime=lifetime)
            newer, _ = subject._read(path)
            second = document(newer)
            self.assertEqual(second["conversation"], first["conversation"])
            self.assertEqual(second["lifetime"], first["lifetime"])
            self.assertNotEqual(second["revision"], first["revision"])
            before = subject.state_image()
            await chats.settle(request, previous, None, fingerprint, False, lifetime=lifetime)
            self.assertEqual(subject.state_image(), before)
            # Check that the observed route actually removes an entry when
            # the exact same conversation and current revision are supplied.
            await chats.settle(request, {**previous, "continuedMapRevision": second["revision"]},
                               None, fingerprint, False, lifetime=lifetime)
            self.assertFalse(os.path.lexists(path))
            self.assertEqual(await subscriptions.identity(identifier), proof)
            subject.check_inputs()
        finally:
            state.close()
