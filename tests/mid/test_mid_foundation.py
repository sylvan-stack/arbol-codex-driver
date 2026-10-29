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

# LOW TIER — DO NOT ENABLE OR RECREATE
# Historical examples only. Read before adding related tests; never execute.
# LOW-TIER-BEGIN: tests/mid/test_mid_foundation.py::Foundation.test_arguments_settings_environment_and_error_sanitization
# Reason: Routine argument/settings/catalog/identity/history field mapping is already exercised by retained real account, history, native-schema and owner-configuration workflows. This body adds no distinct difficult invariant under the raised bar. Case reviewed: Arguments settings environment and error sanitization.
# Source: arbol-codex-driver@0c596c5960c34039bd48d05df9b66b4ea9f31680:tests/mid/test_mid_foundation.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     def test_arguments_settings_environment_and_error_sanitization(self) -> None:
#         command = parse_arguments(["--state-dir=/a b", "run", "hello", "--label", "x=y", "--label=z=", "--control"])
#         self.assertEqual(command.options["state-dir"], "/a b")
#         self.assertEqual(command.options["label"], ["x=y", "z="])
#         for args in (
#             [],
#             ["--build", "1", "info"],
#             ["info", "--control"],
#             ["run", "--output", "other"],
#             ["runs", "stop"],
#             ["info", "--state-dir", "--bad"],
#         ):
#             with self.assertRaises(Failure):
#                 parse_arguments(args)
#         settings = self.folder / "settings.json"
#         settings.write_text('{"toolPath":"/tool", "subscriptions":{"work":{"defaultModel":"a","settings":{"future":"x"}}}}')
#         config, notices = read_settings(settings)
#         self.assertEqual((config["toolPath"], notices), ("/tool", []))
#         for text, field in (
#             ('{"toolPath":"/tool", "unknown":"private-sentinel"}', "unknown"),
#             ('{"defaultSubscripton":"private-sentinel"}', "defaultSubscripton"),
#             ('{"subscriptions":{"work":{"defaultModle":"private-sentinel"}}}', "subscriptions.work.defaultModle"),
#             ('{"subscriptions":{"work":{"secret":{"from":"keychain","account":"private-sentinel"}}}}',
#              "subscriptions.work.secret.account"),
#         ):
#             settings.write_text(text)
#             with self.subTest(field=field), self.assertRaises(Failure) as caught:
#                 read_settings(settings)
#             self.assertEqual(caught.exception.result["code"], "invalid_input")
#             self.assertIn(str(settings), str(caught.exception))
#             self.assertIn(field, str(caught.exception))
#             self.assertNotIn("private-sentinel", str(caught.exception))
#         settings.write_text('{"toolPath":false}')
#         with self.assertRaises(Failure):
#             read_settings(settings)
#         env = clean_environment(
#             {
#                 "PATH": "/usr/bin:/bin",
#                 "HOME": "/wrong",
#                 "OPENAI_API_KEY": "secret",
#                 "CODEX_TOKEN": "secret",
#                 "NODE_OPTIONS": "bad",
#                 "ARBOL_TEST_TIME_SCALE": "100",
#                 "LANG": "C",
#             },
#             "/owner",
#             "/private",
#         )
#         self.assertEqual(env, {"PATH": "/usr/bin:/bin", "LANG": "C", "HOME": "/owner", "CODEX_HOME": "/private"})
#         failure = Failure(
#             "tool_failed",
#             "keep secret",
#             {"detail": {"basis": "fields", "excerpt": "🌲" * 3000 + "secret"}, "retryAfterSeconds": 2},
#             ("secret",),
#         )
#         self.assertNotIn("secret", dumps(failure.result))
#         self.assertLessEqual(len(utf8(str(object_value(failure.result["detail"])["excerpt"]))), 1024)
#         self.assertNotIn("retryAfterSeconds", failure.result)
#         self.assertEqual(safe_failure(ValueError("private"))["code"], "internal")
#         for scale in ("", "0", "-1", "nan", "Infinity", "no"):
#             with self.assertRaises(Failure):
#                 fixed_wait(10, {"ARBOL_TEST_TIME_SCALE": scale})
#         self.assertEqual(fixed_wait(100, {"ARBOL_TEST_TIME_SCALE": "2"}), 0.05)
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_foundation.py::Foundation.test_build_identity_ignores_cwd_and_rejects_invalid_metadata
# Reason: Routine argument/settings/catalog/identity/history field mapping is already exercised by retained real account, history, native-schema and owner-configuration workflows. This body adds no distinct difficult invariant under the raised bar. Case reviewed: Build identity ignores cwd and rejects invalid metadata.
# Source: arbol-codex-driver@0c596c5960c34039bd48d05df9b66b4ea9f31680:tests/mid/test_mid_foundation.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     def test_build_identity_ignores_cwd_and_rejects_invalid_metadata(self) -> None:
#         folder = self.folder / "artifact"
#         folder.mkdir()
#         write_json(folder / "build.json", {"component": "arbol-codex-driver", "build": "a", "packageVersion": "1.2.3"})
#         self.assertEqual(build_identity(folder), {"version": "1.2.3", "build": "a"})
#         write_json(folder / "build.json", {"component": "other", "build": "a", "packageVersion": "1.2.3"})
#         with self.assertRaises(Failure):
#             build_identity(folder)
#         (folder / "build.json").write_text("null")
#         with self.assertRaises(Failure):
#             build_identity(folder)
#         self.assertEqual(build_identity()["version"], "1.0.0")
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_foundation.py::Foundation.test_history_native_pairing_shell_fields_and_private_ordered_images
# Reason: Routine argument/settings/catalog/identity/history field mapping is already exercised by retained real account, history, native-schema and owner-configuration workflows. This body adds no distinct difficult invariant under the raised bar. Case reviewed: History native pairing shell fields and private ordered images.
# Source: arbol-codex-driver@0c596c5960c34039bd48d05df9b66b4ea9f31680:tests/mid/test_mid_foundation.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     def test_history_native_pairing_shell_fields_and_private_ordered_images(self) -> None:
#         history: list[Object] = [
#             {"type": "message", "role": "user", "text": "old", "images": [{"mediaType": "image/png", "data": "aQ=="}]},
#             {
#                 "type": "tool_call",
#                 "name": "shell",
#                 "input": {"command": "pwd", "cwd": "/work", "vendorOnly": "removed"},
#                 "ok": False,
#                 "result": {"output": "out", "exitCode": 2},
#                 "error": "bad",
#             },
#             {"type": "message", "role": "assistant", "text": "reply"},
#         ]
#         items = history_items(history)
#         call, result = object_value(items[1]), object_value(items[2])
#         self.assertEqual(call["call_id"], result["call_id"])
#         self.assertRegex(str(call["call_id"]), r"^call_[a-zA-Z0-9]{24}$")
#         self.assertEqual(loads(str(call["arguments"])), {"command": "pwd", "cwd": "/work"})
#         self.assertEqual(result["output"], "out\nexit code: 2\nbad")
#         rebuilt = labelled_history_input(
#             history, {"text": "new", "images": [{"mediaType": "image/jpeg", "data": "b2s="}]}
#         )
#         self.assertIn("New message:\n\nnew", str(rebuilt["text"]))
#         inputs = prepare_turn_input(rebuilt, self.folder)
#         self.assertEqual(inputs[0], {"type": "text", "text": rebuilt["text"]})
#         for index, raw in enumerate(inputs[1:]):
#             file = Path(str(object_value(raw)["path"]))
#             self.assertEqual(file.read_bytes(), [b"i", b"ok"][index])
#             self.assertEqual(file.stat().st_mode & 0o777, 0o600)
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_foundation.py::Foundation.test_catalog_pagination_fallback_usage_and_unknown_identifiers
# Reason: Routine argument/settings/catalog/identity/history field mapping is already exercised by retained real account, history, native-schema and owner-configuration workflows. This body adds no distinct difficult invariant under the raised bar. Case reviewed: Catalog pagination fallback usage and unknown identifiers.
# Source: arbol-codex-driver@0c596c5960c34039bd48d05df9b66b4ea9f31680:tests/mid/test_mid_foundation.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_catalog_pagination_fallback_usage_and_unknown_identifiers(self) -> None:
#         self.assertEqual(
#             normalize_account({"account": {"type": "chatgpt", "email": "u", "planType": "future", "secret": "unused"}}),
#             {"email": "u", "plan": "future"},
#         )
#         self.assertIsNone(normalize_account({"account": {"type": "apiKey"}}))
#         usage = normalize_usage(
#             {
#                 "rateLimits": {
#                     "primary": {"usedPercent": 110, "windowDurationMins": 1440},
#                     "secondary": {"usedPercent": None},
#                     "planType": None,
#                 }
#             },
#             "plus",
#             now(),
#         )
#         self.assertEqual(
#             usage["windows"],
#             [
#                 {
#                     "kind": "other",
#                     "label": "1-day window",
#                     "usedPercent": 100,
#                     "windowMinutes": 1440,
#                     "limitReached": True,
#                 },
#                 {"kind": "other", "label": "Usage window"},
#             ],
#         )
#         model: Object = {
#             "id": "one",
#             "displayName": "One",
#             "hidden": False,
#             "supportedReasoningEfforts": [{"reasoningEffort": "future"}],
#             "defaultReasoningEffort": "future",
#             "isDefault": False,
#             "serviceTiers": [{"id": "future"}],
#         }
#         models = normalize_models([model, {**model, "id": "hidden", "hidden": True}, model])
#         self.assertEqual(len(cast(list[Json], models["models"])), 1)
#         requests: list[Json] = []
#
#         async def request(method: str, params: Json) -> Json:
#             requests.append(params)
#             return {"data": [model], "nextCursor": "next" if len(requests) == 1 else None}
#
#         self.assertEqual((await read_model_catalog(request))["source"], "tool")
#         self.assertEqual(requests, [{"includeHidden": False}, {"includeHidden": False, "cursor": "next"}])
#
#         async def cyclic(method: str, params: Json) -> Json:
#             return {"data": [model], "nextCursor": "same"}
#
#         self.assertEqual((await read_model_catalog(cyclic))["source"], "builtin")
#
#         async def rejected(method: str, params: Json) -> Json:
#             raise Failure("credential_rejected", "Expired")
#
#         with self.assertRaises(Failure):
#             await read_model_catalog(rejected)
#         self.assertEqual(len(cast(list[Json], builtin_catalog()["models"])), 7)
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_foundation.py::Foundation.test_usage_windows_carry_no_resource_the_app_server_does_not_state
# Reason: Routine argument/settings/catalog/identity/history field mapping is already exercised by retained real account, history, native-schema and owner-configuration workflows. This body adds no distinct difficult invariant under the raised bar. Case reviewed: Usage windows carry no resource the app server does not state.
# Source: arbol-codex-driver@0c596c5960c34039bd48d05df9b66b4ea9f31680:tests/mid/test_mid_foundation.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     def test_usage_windows_carry_no_resource_the_app_server_does_not_state(self) -> None:
#         # DRV-1.27, CDX-1.16, CDX-D31: `account/rateLimits/read` names no unit for a window, so `resource` is never
#         # invented; the account's credit balance is a snapshot field, not a window's unit, and stays in `extra`.
#         usage = normalize_usage(
#             {
#                 "rateLimits": {
#                     "primary": {"usedPercent": 10, "windowDurationMins": 300, "resetsAt": 2000},
#                     "secondary": {"usedPercent": 95, "windowDurationMins": 10080},
#                     "credits": {"hasCredits": True, "unlimited": False, "balance": "12.5"},
#                     "planType": "pro",
#                 }
#             },
#             None,
#             now(),
#         )
#         windows = usage["windows"]
#         assert isinstance(windows, list)
#         self.assertEqual([object_value(window)["kind"] for window in windows], ["session", "weekly"])
#         for window in windows:
#             self.assertNotIn("resource", object_value(window))
#         self.assertEqual(object_value(usage["extra"])["credits"], {"hasCredits": True, "unlimited": False, "balance": "12.5"})
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_foundation.py::FamilySettings.test_an_unknown_family_setting_refuses_and_is_named
# Reason: Routine argument/settings/catalog/identity/history field mapping is already exercised by retained real account, history, native-schema and owner-configuration workflows. This body adds no distinct difficult invariant under the raised bar. Case reviewed: An unknown family setting refuses and is named.
# Source: arbol-codex-driver@0c596c5960c34039bd48d05df9b66b4ea9f31680:tests/mid/test_mid_foundation.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_an_unknown_family_setting_refuses_and_is_named(self) -> None:
#         temporary = tempfile.TemporaryDirectory(prefix="codex-family-settings-")
#         self.addCleanup(temporary.cleanup)
#         folder = Path(temporary.name)
#         state = State(folder / "state")
#         state.initialize()
#         file = folder / "settings.json"
#         self.assertEqual((await Subscriptions(state, {}, [], file, {}).get("chatgpt"))["settings"], {})
#         settings: Object = {"subscriptions": {"chatgpt": {"settings": {"future": "private-sentinel"}}}}
#         with self.assertRaises(Failure) as caught:
#             await Subscriptions(state, settings, [], file, {}).get("chatgpt")
#         self.assertEqual(caught.exception.result["code"], "invalid_input")
#         self.assertIn(f"{file}: unknown field subscriptions.chatgpt.settings.future", str(caught.exception))
#         self.assertNotIn("private-sentinel", str(caught.exception))
# LOW-TIER-SOURCE-END
# LOW-TIER-END
