"""Commented mid-tier selections; see MID_TIER.md before restoring a case."""

# Restore the needed imports and class header only for an explicit testing task.
# import test_app_server as _support
# from test_app_server import (
#     AppServer,
#     AppServerTests,
#     Cancellation,
#     FAKE,
#     Failure,
#     Object,
#     OutputTests,
#     Path,
#     asyncio,
#     loads,
#     object_value,
#     patch,
#     shlex,
#     sys,
#     tempfile,
#     time,
#     unittest,
# )


# class AppServerTests(_support.AppServerTests):
# TEST-TIER-DISABLED-BEGIN tests/test_app_server.py::AppServerTests.test_private_home_configuration_clean_environment_and_owner_cleanup
#     async def test_private_home_configuration_clean_environment_and_owner_cleanup(self) -> None:
#         server = await self.start()
#         self.assertTrue(await owner_alive(server.owner))
#         records = self.records()
#         env = object_value(records[0]["env"])
#         self.assertEqual(env["HOME"], self.env["HOME"])
#         self.assertEqual(env["CODEX_HOME"], str(self.home))
#         self.assertNotIn("OPENAI_API_KEY", env)
#         self.assertNotIn("CODEX_TOKEN", env)
#         self.assertNotIn("ARBOL_OTHER", env)
#         self.assertEqual(records[0]["cwd"], str(self.home.resolve()))
#         self.assertEqual([record.get("method") for record in records[1:]], ["initialize", "initialized", "config/read"])
#         self.assertEqual((self.home / "config.toml").read_text(), DRIVER_CONFIG)
#         self.assertEqual(self.home.stat().st_mode & 0o777, 0o700)
#         self.assertEqual((self.home / "config.toml").stat().st_mode & 0o777, 0o600)
#         await server.close()
#         self.assertFalse(await owner_alive(server.owner))
# TEST-TIER-DISABLED-END tests/test_app_server.py::AppServerTests.test_private_home_configuration_clean_environment_and_owner_cleanup

# TEST-TIER-DISABLED-BEGIN tests/test_app_server.py::AppServerTests.test_handshake_version_and_effective_configuration_are_enforced
#     async def test_handshake_version_and_effective_configuration_are_enforced(self) -> None:
#         for scenario, code in (("old-handshake", "tool_unsupported"), ("bad-handshake", "tool_failed"),
#                                ("wrong-config", "tool_unsupported")):
#             with self.subTest(scenario=scenario), self.assertRaises(Failure) as caught:
#                 await self.start(scenario)
#             self.assertEqual(caught.exception.result["code"], code)
#             if scenario == "old-handshake":
#                 self.assertEqual(object_value(caught.exception.result["detail"])["toolVersion"], "0.158.0")
#                 self.assertEqual(object_value(caught.exception.result["detail"])["neededVersion"], "0.159.2")
# TEST-TIER-DISABLED-END tests/test_app_server.py::AppServerTests.test_handshake_version_and_effective_configuration_are_enforced

# TEST-TIER-DISABLED-BEGIN tests/test_app_server.py::AppServerTests.test_fragmented_utf8_early_notifications_burst_and_unknown_request
#     async def test_fragmented_utf8_early_notifications_burst_and_unknown_request(self) -> None:
#         server = await self.start()
#         self.assertEqual(await server.request("fragmented", {}), {"text": "café🌲"})
#         await server.request("early", {})
#         self.assertEqual(
#             await server.wait_for_notification(
#                 "account/login/completed", lambda value: object_value(value).get("loginId") == "wanted"
#             ),
#             {"loginId": "wanted", "success": True},
#         )
#         self.assertEqual(
#             await server.wait_for_notification("account/login/completed"), {"loginId": "other", "success": False}
#         )
#         await server.request("burst", {})
#         for seq in range(600):
#             notice = await server.next_notification()
#             self.assertEqual((notice.method, notice.params), ("fixture/delta", {"seq": seq}))
#         self.assertEqual(
#             await server.request("unknown", {}), {"code": -32601, "message": "Method not supported by the Driver."}
#         )
# TEST-TIER-DISABLED-END tests/test_app_server.py::AppServerTests.test_fragmented_utf8_early_notifications_burst_and_unknown_request

# TEST-TIER-DISABLED-BEGIN tests/test_app_server.py::AppServerTests.test_malformed_oversized_boolean_id_exit_and_internal_request_timeout
#     async def test_malformed_oversized_boolean_id_exit_and_internal_request_timeout(self) -> None:
#         for method in ("malformed", "oversized", "boolean-id", "exit", "hang", "overflow"):
#             server = await self.start()
#             with self.subTest(method=method), self.assertRaises(Failure) as caught:
#                 await server.request(method, {}, timeout=0.15)
#             self.assertEqual(caught.exception.result["code"], "tool_failed")
#             await server.close(force_at=time.monotonic() + 0.1)
#             self.assertFalse(await owner_alive(server.owner))
# TEST-TIER-DISABLED-END tests/test_app_server.py::AppServerTests.test_malformed_oversized_boolean_id_exit_and_internal_request_timeout

# TEST-TIER-DISABLED-BEGIN tests/test_app_server.py::AppServerTests.test_cancelled_request_leaves_transport_available_and_preabort_sends_nothing
#     async def test_cancelled_request_leaves_transport_available_and_preabort_sends_nothing(self) -> None:
#         server = await self.start()
#         cancellation = Cancellation()
#         pending = asyncio.create_task(server.request("hang", {}, cancellation=cancellation))
#         waiting = asyncio.create_task(server.wait_for_notification("never", cancellation=cancellation))
#         await asyncio.sleep(0.02)
#         cancellation.abort()
#         for task in (pending, waiting):
#             with self.assertRaises(Failure):
#                 await task
#         count = len(self.records())
#         with self.assertRaises(Failure):
#             await server.request("pre-aborted", {}, cancellation=cancellation)
#         self.assertEqual(len(self.records()), count)
#         self.assertEqual(await server.request("account/login/cancel", {}), {"ok": True})
# TEST-TIER-DISABLED-END tests/test_app_server.py::AppServerTests.test_cancelled_request_leaves_transport_available_and_preabort_sends_nothing

# TEST-TIER-DISABLED-BEGIN tests/test_app_server.py::AppServerTests.test_startup_wrong_home_config_and_cancellation_gives_eof_before_force
#     async def test_startup_wrong_home_config_and_cancellation_gives_eof_before_force(self) -> None:
#         for scenario in ("wrong-home", "wrong-config", "hang-initialize-linger", "hang-config-linger"):
#             cancellation = Cancellation()
#             owners: list[Owner] = []
#
#             async def spawned(owner: Owner, owners: list[Owner] = owners) -> None:
#                 owners.append(owner)
#
#             opening = asyncio.create_task(
#                 AppServer.start(
#                     tool_path=self.program(scenario),
#                     home=self.home,
#                     env=self.env,
#                     request_timeout=3,
#                     cancellation=cancellation,
#                     on_spawn=spawned,
#                 )
#             )
#             if scenario.startswith("hang"):
#                 method = "initialize" if scenario.startswith("hang-initialize") else "config/read"
#                 deadline = time.monotonic() + 2
#                 while not self.log.exists() or not any(record.get("method") == method for record in self.records()):
#                     self.assertLess(time.monotonic(), deadline)
#                     await asyncio.sleep(0.005)
#                 stopped = time.monotonic()
#                 cancellation.abort()
#             with self.assertRaises(Failure):
#                 await opening
#             self.assertTrue(owners)
#             self.assertFalse(await owner_alive(owners[0]))
#             if scenario.startswith("hang"):
#                 elapsed = time.monotonic() - stopped
#                 self.assertGreaterEqual(elapsed, 0.19)
#                 self.assertLess(elapsed, 0.7)
#                 self.assertTrue(any(record.get("stage") == "stdinEOF" for record in self.records()))
#             self.log.unlink(missing_ok=True)
# TEST-TIER-DISABLED-END tests/test_app_server.py::AppServerTests.test_startup_wrong_home_config_and_cancellation_gives_eof_before_force

# TEST-TIER-DISABLED-BEGIN tests/test_app_server.py::AppServerTests.test_authentication_rejection_is_specific_and_diagnostics_are_bounded
#     async def test_authentication_rejection_is_specific_and_diagnostics_are_bounded(self) -> None:
#         server = await self.start()
#         for method, code in (
#             ("rpc-error", "credential_rejected"),
#             ("structured-error", "credential_rejected"),
#             ("unknown-error", "tool_failed"),
#         ):
#             with self.assertRaises(Failure) as caught:
#                 await server.request(method, {})
#             self.assertEqual(caught.exception.result["code"], code)
#         with self.assertRaises(Failure) as caught:
#             await server.request("exit-log", {})
#         excerpt = str(object_value(caught.exception.result.get("detail")).get("excerpt", ""))
#         self.assertTrue(excerpt.endswith("diagnostic-sentinel"))
#         self.assertLessEqual(len(utf8(excerpt)), 1024)
#         self.assertNotIn("�", excerpt)
# TEST-TIER-DISABLED-END tests/test_app_server.py::AppServerTests.test_authentication_rejection_is_specific_and_diagnostics_are_bounded

# TEST-TIER-DISABLED-BEGIN tests/test_app_server.py::AppServerTests.test_cleanup_survives_capture_failure_and_ends_ignoring_descendant
#     async def test_cleanup_survives_capture_failure_and_ends_ignoring_descendant(self) -> None:
#         server = await self.start()
#         pid = object_value(await server.request("spawn-child", {}))["pid"]
#         child = await process_owner(cast(int, pid))
#         assert child is not None
#         with patch.object(server, "capture_process_groups", side_effect=Failure("internal", "capture failed")):
#             with self.assertRaises(Failure):
#                 await server.end(force_at=time.monotonic() + 0.1)
#         self.assertFalse(await owner_alive(server.owner))
#         for _ in range(20):
#             if not await owner_alive(child):
#                 break
#             await asyncio.sleep(0.01)
#         self.assertFalse(await owner_alive(child))
#         self.servers.remove(server)
# TEST-TIER-DISABLED-END tests/test_app_server.py::AppServerTests.test_cleanup_survives_capture_failure_and_ends_ignoring_descendant

# TEST-TIER-DISABLED-BEGIN tests/test_app_server.py::AppServerTests.test_predicate_errors_settle_only_affected_waiter
#     async def test_predicate_errors_settle_only_affected_waiter(self) -> None:
#         server = await self.start()
#
#         def bad(value: Json) -> bool:
#             raise ValueError("predicate")
#
#         waiting = asyncio.create_task(server.wait_for_notification("account/login/completed", bad))
#         await asyncio.sleep(0)
#         await server.request("early", {})
#         with self.assertRaises(ValueError):
#             await waiting
#         self.assertEqual((await server.next_notification()).params, {"loginId": "other", "success": False})
#         self.assertIsNone(server.failure)
# TEST-TIER-DISABLED-END tests/test_app_server.py::AppServerTests.test_predicate_errors_settle_only_affected_waiter

# TEST-TIER-DISABLED-BEGIN tests/test_app_server.py::AppServerTests.test_notification_backpressure_preserves_long_stream_and_wakes_for_rpc
#     async def test_notification_backpressure_preserves_long_stream_and_wakes_for_rpc(self) -> None:
#         server = await self.start()
#         await server.request("burst-first", {})
#         await asyncio.sleep(0.08)
#         self.assertLessEqual(len(server.notifications), 4096)
#         self.assertGreater(len(server.notifications), 0)
#         total = 0
#         while total < 5000:
#             notice = await server.next_notification(timeout=1)
#             self.assertEqual(notice.params, {"seq": total})
#             total += 1
#         self.assertEqual(await server.request("ping", {}), {"ok": True})
# TEST-TIER-DISABLED-END tests/test_app_server.py::AppServerTests.test_notification_backpressure_preserves_long_stream_and_wakes_for_rpc



# class OutputTests(_support.OutputTests):
# TEST-TIER-DISABLED-BEGIN tests/test_app_server.py::OutputTests.test_serialized_output_gapless_events_lone_surrogates_and_cancelled_blocked_flush
#     async def test_serialized_output_gapless_events_lone_surrogates_and_cancelled_blocked_flush(self) -> None:
#         read, write = os.pipe()
#         output = Output(write)
#         events = EventStream(output)
#         try:
#             events.emit("started")
#             events.emit("text", {"text": "\ud800"})
#             await events.finish()
#             raw = os.read(read, 8192).decode()
#             records = [object_value(loads(line)) for line in raw.splitlines()]
#             self.assertEqual([record["seq"] for record in records], [1, 2, 3])
#             self.assertEqual([record["type"] for record in records], ["started", "text", "finished"])
#             events.emit("text", {"text": "late"})
#             self.assertEqual(events.sequence, 3)
#             blocked = EventStream(output)
#             blocked.emit("text", {"text": "x" * (1024 * 1024)})
#             cancellation = Cancellation()
#             task = asyncio.create_task(blocked.flush(cancellation))
#             await asyncio.sleep(0.02)
#             cancellation.abort()
#             with self.assertRaises(Failure):
#                 await asyncio.wait_for(task, 0.3)
#             blocked.abandon()
#             self.assertTrue(output.abandoned)
#             await asyncio.gather(*blocked.tasks, return_exceptions=True)
#         finally:
#             output.abandon()
#             os.close(read)
# TEST-TIER-DISABLED-END tests/test_app_server.py::OutputTests.test_serialized_output_gapless_events_lone_surrogates_and_cancelled_blocked_flush

# TEST-TIER-DISABLED-BEGIN tests/test_app_server.py::OutputTests.test_broken_output_aborts_writer_and_text_mode_uses_node_unicode_replacement
#     async def test_broken_output_aborts_writer_and_text_mode_uses_node_unicode_replacement(self) -> None:
#         read, write = os.pipe()
#         output = Output(write)
#         events = EventStream(output)
#         events.text_only = True
#         try:
#             events.emit("text", {"text": "\ud800\ud83d\ude00"})
#             await events.flush()
#             self.assertEqual(os.read(read, 8192), "�😀".encode())
#             os.close(read)
#             stopped = asyncio.Event()
#             output.on_error = stopped.set
#             events.emit("text", {"text": "broken"})
#             with self.assertRaises(BrokenPipeError):
#                 await events.flush()
#             self.assertTrue(stopped.is_set())
#         finally:
#             output.abandon()
# TEST-TIER-DISABLED-END tests/test_app_server.py::OutputTests.test_broken_output_aborts_writer_and_text_mode_uses_node_unicode_replacement


# Original deferred imports (restore at the required scope, never blindly at the tail).
# TEST-TIER-IMPORTS-BEGIN tests/test_app_server.py:2
# import os
# TEST-TIER-IMPORTS-END tests/test_app_server.py:2

# TEST-TIER-IMPORTS-BEGIN tests/test_app_server.py:9
# from typing import cast
# TEST-TIER-IMPORTS-END tests/test_app_server.py:9

# TEST-TIER-IMPORTS-BEGIN tests/test_app_server.py:12
# from arbol_codex_driver.app_server import DRIVER_CONFIG, AppServer
# TEST-TIER-IMPORTS-END tests/test_app_server.py:12

# TEST-TIER-IMPORTS-BEGIN tests/test_app_server.py:15
# from arbol_codex_driver.event_stream import EventStream, Output
# TEST-TIER-IMPORTS-END tests/test_app_server.py:15

# TEST-TIER-IMPORTS-BEGIN tests/test_app_server.py:16
# from arbol_codex_driver.json_types import Json, Object, loads, object_value, utf8
# TEST-TIER-IMPORTS-END tests/test_app_server.py:16

# TEST-TIER-IMPORTS-BEGIN tests/test_app_server.py:17
# from arbol_codex_driver.state import Owner, owner_alive, process_owner
# TEST-TIER-IMPORTS-END tests/test_app_server.py:17

raise RuntimeError("Mid-tier tests require an explicitly requested testing task; see MID_TIER.md.")
