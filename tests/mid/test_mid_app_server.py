"""Mid-tier selections. Write or run only in an explicitly requested testing task."""
from __future__ import annotations

import test_app_server as _support
from test_app_server import (AppServer ,Cancellation ,Failure ,Owner ,asyncio ,cast ,object_value ,owner_alive ,patch ,process_owner ,time)


class AppServerTests(_support.AppServerTests):


# TEST-TIER-BEGIN tests/test_app_server.py::AppServerTests.test_fragmented_utf8_early_notifications_burst_and_unknown_request
    async def test_fragmented_utf8_early_notifications_burst_and_unknown_request(self) -> None:
        server = await self.start()
        self.assertEqual(await server.request("fragmented", {}), {"text": "café🌲"})
        await server.request("early", {})
        self.assertEqual(
            await server.wait_for_notification(
                "account/login/completed", lambda value: object_value(value).get("loginId") == "wanted"
            ),
            {"loginId": "wanted", "success": True},
        )
        self.assertEqual(
            await server.wait_for_notification("account/login/completed"), {"loginId": "other", "success": False}
        )
        await server.request("burst", {})
        for seq in range(600):
            notice = await server.next_notification()
            self.assertEqual((notice.method, notice.params), ("fixture/delta", {"seq": seq}))
        self.assertEqual(
            await server.request("unknown", {}), {"code": -32601, "message": "Method not supported by the Driver."}
        )
# TEST-TIER-END tests/test_app_server.py::AppServerTests.test_fragmented_utf8_early_notifications_burst_and_unknown_request

# TEST-TIER-BEGIN tests/test_app_server.py::AppServerTests.test_malformed_oversized_boolean_id_exit_and_internal_request_timeout
    async def test_malformed_oversized_boolean_id_exit_and_internal_request_timeout(self) -> None:
        for method in ("malformed", "oversized", "boolean-id", "exit", "hang", "overflow"):
            server = await self.start()
            with self.subTest(method=method), self.assertRaises(Failure) as caught:
                await server.request(method, {}, timeout=0.15)
            self.assertEqual(caught.exception.result["code"], "tool_failed")
            await server.close(force_at=time.monotonic() + 0.1)
            self.assertFalse(await owner_alive(server.owner))
# TEST-TIER-END tests/test_app_server.py::AppServerTests.test_malformed_oversized_boolean_id_exit_and_internal_request_timeout

# TEST-TIER-BEGIN tests/test_app_server.py::AppServerTests.test_cancelled_request_leaves_transport_available_and_preabort_sends_nothing
    async def test_cancelled_request_leaves_transport_available_and_preabort_sends_nothing(self) -> None:
        server = await self.start()
        cancellation = Cancellation()
        pending = asyncio.create_task(server.request("hang", {}, cancellation=cancellation))
        waiting = asyncio.create_task(server.wait_for_notification("never", cancellation=cancellation))
        await asyncio.sleep(0.02)
        cancellation.abort()
        for task in (pending, waiting):
            with self.assertRaises(Failure):
                await task
        count = len(self.records())
        with self.assertRaises(Failure):
            await server.request("pre-aborted", {}, cancellation=cancellation)
        self.assertEqual(len(self.records()), count)
        self.assertEqual(await server.request("account/login/cancel", {}), {"ok": True})
# TEST-TIER-END tests/test_app_server.py::AppServerTests.test_cancelled_request_leaves_transport_available_and_preabort_sends_nothing

# TEST-TIER-BEGIN tests/test_app_server.py::AppServerTests.test_startup_wrong_home_config_and_cancellation_gives_eof_before_force
    async def test_startup_wrong_home_config_and_cancellation_gives_eof_before_force(self) -> None:
        for scenario in ("wrong-home", "wrong-config", "hang-initialize-linger", "hang-config-linger"):
            cancellation = Cancellation()
            owners: list[Owner] = []

            async def spawned(owner: Owner, owners: list[Owner] = owners) -> None:
                owners.append(owner)

            opening = asyncio.create_task(
                AppServer.start(
                    tool_path=self.program(scenario),
                    home=self.home,
                    env=self.env,
                    request_timeout=3,
                    cancellation=cancellation,
                    on_spawn=spawned,
                )
            )
            if scenario.startswith("hang"):
                method = "initialize" if scenario.startswith("hang-initialize") else "config/read"
                deadline = time.monotonic() + 2
                while not self.log.exists() or not any(record.get("method") == method for record in self.records()):
                    self.assertLess(time.monotonic(), deadline)
                    await asyncio.sleep(0.005)
                stopped = time.monotonic()
                cancellation.abort()
            with self.assertRaises(Failure):
                await opening
            self.assertTrue(owners)
            self.assertFalse(await owner_alive(owners[0]))
            if scenario.startswith("hang"):
                elapsed = time.monotonic() - stopped
                self.assertGreaterEqual(elapsed, 0.19)
                self.assertLess(elapsed, 0.7)
                self.assertTrue(any(record.get("stage") == "stdinEOF" for record in self.records()))
            self.log.unlink(missing_ok=True)
# TEST-TIER-END tests/test_app_server.py::AppServerTests.test_startup_wrong_home_config_and_cancellation_gives_eof_before_force


# TEST-TIER-BEGIN tests/test_app_server.py::AppServerTests.test_cleanup_survives_capture_failure_and_ends_ignoring_descendant
    async def test_cleanup_survives_capture_failure_and_ends_ignoring_descendant(self) -> None:
        server = await self.start()
        pid = object_value(await server.request("spawn-child", {}))["pid"]
        child = await process_owner(cast(int, pid))
        assert child is not None
        with patch.object(server, "capture_process_groups", side_effect=Failure("internal", "capture failed")):
            with self.assertRaises(Failure):
                await server.end(force_at=time.monotonic() + 0.1)
        self.assertFalse(await owner_alive(server.owner))
        for _ in range(20):
            if not await owner_alive(child):
                break
            await asyncio.sleep(0.01)
        self.assertFalse(await owner_alive(child))
        self.servers.remove(server)
# TEST-TIER-END tests/test_app_server.py::AppServerTests.test_cleanup_survives_capture_failure_and_ends_ignoring_descendant


# TEST-TIER-BEGIN tests/test_app_server.py::AppServerTests.test_notification_backpressure_preserves_long_stream_and_wakes_for_rpc
    async def test_notification_backpressure_preserves_long_stream_and_wakes_for_rpc(self) -> None:
        server = await self.start()
        await server.request("burst-first", {})
        await asyncio.sleep(0.08)
        self.assertLessEqual(len(server.notifications), 4096)
        self.assertGreater(len(server.notifications), 0)
        total = 0
        while total < 5000:
            notice = await server.next_notification(timeout=1)
            self.assertEqual(notice.params, {"seq": total})
            total += 1
        self.assertEqual(await server.request("ping", {}), {"ok": True})
# TEST-TIER-END tests/test_app_server.py::AppServerTests.test_notification_backpressure_preserves_long_stream_and_wakes_for_rpc
