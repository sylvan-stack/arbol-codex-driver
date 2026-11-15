"""Prospective fixed final H1 local case; no suite/gate/inventory wiring."""
from __future__ import annotations

import asyncio
import os
import stat
import unittest
from dataclasses import dataclass
from typing import ClassVar

from identity_support import H1_ID, CodexH1Support, document, require, sha

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
