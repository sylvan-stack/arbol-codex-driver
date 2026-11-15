"""Prospective local proof and final H1 cases; no gate or inventory wiring."""
from __future__ import annotations

import asyncio
import base64
import json
import os
import stat
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
from arbol_codex_driver.identity_protocol import PrivateDirectory, canonical_bytes, object_fields, parse_bytes, token
from arbol_codex_driver.state import State
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
