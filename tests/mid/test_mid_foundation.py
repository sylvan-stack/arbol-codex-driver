"""Mid-tier selections. Write or run only in an explicitly requested testing task."""
from __future__ import annotations

import test_foundation as _support
from test_foundation import (Chats ,Failure ,Json ,MessageDigest ,Object ,ROOT ,Runs ,asyncio ,atomic_write ,cast ,digest ,dumps ,loads ,message_digest ,now ,object_value ,os ,owner_alive ,owner_json ,parse_owner ,process_owner ,read_json ,read_run_request ,replace ,saved_conversation ,time ,utf8 ,write_json)


class Foundation(_support.Foundation):
# TEST-TIER-BEGIN tests/test_foundation.py::Foundation.test_state_private_layout_higher_format_and_safe_ids
    def test_state_private_layout_higher_format_and_safe_ids(self) -> None:
        self.assertEqual((self.state.directory / "format").read_text(), "1\n")
        self.assertEqual(self.state.directory.stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.state.directory / "format").stat().st_mode & 0o777, 0o600)
        for id_ in ("", "../outside", ".", "..", "a/b", "a\\b", "x" * 129):
            with self.subTest(id=id_), self.assertRaises(Failure):
                self.state.subscription(id_)
        for content in ("2\n", "9" * 70 + "\n", "secret malformed", "0", "", "1.0", "-1"):
            path = self.state.directory / "format"
            path.write_text(content)
            path.chmod(0o644)
            self.state.directory.chmod(0o755)
            before = path.stat()
            with self.assertRaises(Failure) as caught:
                self.state.initialize()
            self.assertEqual(
                caught.exception.result["code"],
                "state_newer" if content.strip().isdigit() and int(content) > 1 else "internal",
            )
            self.assertNotIn("secret malformed", str(caught.exception))
            self.assertEqual(path.read_text(), content)
            self.assertEqual(path.stat().st_ino, before.st_ino)
            self.assertEqual(path.stat().st_mode & 0o777, 0o644)
            self.assertEqual(self.state.directory.stat().st_mode & 0o777, 0o755)
# TEST-TIER-END tests/test_foundation.py::Foundation.test_state_private_layout_higher_format_and_safe_ids

# TEST-TIER-BEGIN tests/test_foundation.py::Foundation.test_state_lock_serializes_and_reclaims_dead_owner
    async def test_state_lock_serializes_and_reclaims_dead_owner(self) -> None:
        directory = self.state.subscription("account")
        write_json(directory / "lock", {"owner": {"pid": 2147483647, "startedAt": "2000-01-01T00:00:00Z"}})
        count = 0

        async def increment() -> None:
            nonlocal count
            previous = count
            await asyncio.sleep(0.002)
            count = previous + 1

        await asyncio.gather(*(self.state.with_subscription_lock("account", increment) for _ in range(8)))
        self.assertEqual(count, 8)
        self.assertFalse((directory / "lock").exists())
        self.assertEqual(list(directory.glob(".write-*")), [])
        own = await process_owner(os.getpid())
        assert own is not None
        self.assertTrue(await owner_alive(own))
        self.assertFalse(await owner_alive({**own, "startedAt": "1970-01-01T00:00:00.000Z"}))
        for bad in (
            {"pid": True, "startedAt": now()},
            {"pid": 0, "startedAt": now()},
            {"pid": 1, "startedAt": "private"},
        ):
            with self.assertRaises(Failure):
                parse_owner(cast(Json, bad))
# TEST-TIER-END tests/test_foundation.py::Foundation.test_state_lock_serializes_and_reclaims_dead_owner

# TEST-TIER-BEGIN tests/test_foundation.py::Foundation.test_atomic_write_failure_cleanup_and_no_symlink_traversal
    def test_atomic_write_failure_cleanup_and_no_symlink_traversal(self) -> None:
        path = self.state.directory / "record.json"
        atomic_write(path, '{"count":1}')
        self.assertEqual(read_json(path), {"count": 1})
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        destination = self.state.directory / "directory"
        destination.mkdir()
        with self.assertRaises(OSError):
            atomic_write(destination, "data")
        self.assertEqual(list(self.state.directory.glob(".write-*")), [])
        outside = self.folder / "outside"
        outside.mkdir()
        stale = outside / ".write-external"
        stale.write_text("sentinel")
        os.utime(stale, (time.time() - 100, time.time() - 100))
        (self.state.directory / "link").symlink_to(outside, target_is_directory=True)
        own = self.state.directory / ".write-old"
        own.write_text("leftover")
        os.utime(own, (time.time() - 100, time.time() - 100))
        self.state.clear_unfinished_writes()
        self.assertTrue(stale.exists())
        self.assertFalse(own.exists())
# TEST-TIER-END tests/test_foundation.py::Foundation.test_atomic_write_failure_cleanup_and_no_symlink_traversal


# TEST-TIER-BEGIN tests/test_foundation.py::Foundation.test_migration_golden_vectors_and_nonmutating_stream_snapshots
    def test_migration_golden_vectors_and_nonmutating_stream_snapshots(self) -> None:
        fixture = object_value(loads((ROOT / "tests/fixtures/migration-vectors.json").read_text()))
        histories = fixture["histories"]
        assert isinstance(histories, list)
        for raw in histories:
            vector = object_value(raw)
            with self.subTest(vector=vector["name"]):
                expected = object_value(object_value(vector["expected"])["codex"])
                snapshots = expected["snapshots"]
                assert isinstance(snapshots, list)
                history = vector["history"]
                assert isinstance(history, list)
                stream = MessageDigest()
                self.assertEqual(stream.snapshot(), snapshots[0])
                for index, item in enumerate(history):
                    stream.add(object_value(item))
                    self.assertEqual(stream.snapshot(), snapshots[index + 1])
                    self.assertEqual(stream.snapshot(), snapshots[index + 1])
                self.assertEqual(stream.snapshot(), {"messages": expected["messages"], "digest": expected["digest"]})
        json_vectors = object_value(loads((ROOT / "tests/fixtures/migration-json-vectors.json").read_text()))["vectors"]
        assert isinstance(json_vectors, list)
        for raw in json_vectors:
            vector = object_value(raw)
            self.assertEqual(dumps(loads(str(vector["inputJson"]))), vector["expected"])
        self.assertEqual(utf8("\ud800"), b"\xef\xbf\xbd")
        self.assertEqual(dumps("\ud83d\ude00\ud800"), '"😀\\ud800"')
# TEST-TIER-END tests/test_foundation.py::Foundation.test_migration_golden_vectors_and_nonmutating_stream_snapshots

# TEST-TIER-BEGIN tests/test_foundation.py::Foundation.test_continuity_selection_order_conditional_settlement_and_killed_owner
    async def test_continuity_selection_order_conditional_settlement_and_killed_owner(self) -> None:
        work = self.folder / "work"
        work.mkdir()
        request = await read_run_request(
            {"cwd": str(work), "chat-session": "opaque/../chat", "run-id": "selected"}, message="private-new-input"
        )
        request = replace(
            request,
            history=[
                {"type": "message", "role": "user", "text": "private-old"},
                {"type": "message", "role": "assistant", "text": "private-reply"},
            ],
            system_prompt="private-system",
        )
        chats = Chats(self.state)
        key = digest(request.chat_session_id or "")
        home = self.state.subscription("chatgpt") / "home"
        rollout = home / "sessions/2026/10/07/rollout-date-conversation.jsonl"
        rollout.parent.mkdir(parents=True)
        rollout.write_text("vendor content must not be parsed")
        entry: Object = {
            "chatSessionId": request.chat_session_id,
            "conversation": "conversation",
            "workingDirectory": request.working_directory,
            "messages": message_digest(request.history)["messages"],
            "digest": message_digest(request.history)["digest"],
            "systemPromptDigest": digest("private-system"),
            "writtenAt": now(),
        }
        path = chats.path("chatgpt", key)
        write_json(path, entry)
        self.assertEqual((await chats.select(request, home))["continuity"], "resumed")
        self.assertEqual((await chats.select(replace(request, history=[]), home)), {"continuity": "fresh"})
        self.assertEqual(
            (await chats.select(replace(request, chat_session_id=None), home))["rebuildReason"], "no_chat_session"
        )
        for changes, reason in (
            ({"digest": digest("different"), "workingDirectory": "/changed"}, "history_differs"),
            ({"workingDirectory": "/changed", "systemPromptDigest": digest("different")}, "working_folder_changed"),
            ({"systemPromptDigest": digest("different")}, "system_prompt_changed"),
        ):
            write_json(path, {**entry, **changes})
            self.assertEqual((await chats.select(request, home))["rebuildReason"], reason)
        write_json(path, entry)
        rollout.unlink()
        self.assertEqual((await chats.select(request, home))["rebuildReason"], "conversation_gone")
        archived = home / "archived_sessions/nested/rollout-date-conversation.jsonl"
        archived.parent.mkdir(parents=True)
        archived.write_text("malformed vendor content")
        self.assertTrue(saved_conversation(home, "conversation"))
        own = await process_owner(os.getpid())
        assert own is not None
        record: Object = {
            "runId": "occupied",
            "subscriptionId": "chatgpt",
            "owner": owner_json(own),
            "startedAt": now(),
            "conversation": "conversation",
        }
        runs = Runs(self.state)
        runs.save(record)
        self.assertEqual((await chats.select(request, home))["rebuildReason"], "in_use")
        runs.remove("occupied")
        plan = await chats.select(request, home)
        await chats.settle(request, plan, "newer", message_digest(request.history), True)
        await chats.settle(request, plan, None, message_digest(request.history), False)
        self.assertEqual(object_value(chats.entry("chatgpt", key))["conversation"], "newer")
        for content in ("private-new-input", "private-old", "private-reply", "private-system"):
            self.assertNotIn(content, path.read_text())
        record.update(
            {
                "owner": {"pid": os.getpid(), "startedAt": "1970-01-01T00:00:00Z"},
                "chatKey": key,
                "continuedConversation": "newer",
            }
        )
        runs.save(record)
        scratch = self.state.directory / "tmp/occupied"
        scratch.mkdir(parents=True)
        (scratch / "leftover").write_text("scratch")
        self.assertEqual(await runs.list(), [])
        self.assertIsNone(chats.entry("chatgpt", key))
        self.assertFalse(scratch.exists())
# TEST-TIER-END tests/test_foundation.py::Foundation.test_continuity_selection_order_conditional_settlement_and_killed_owner
