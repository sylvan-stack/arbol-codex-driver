"""Individually selected top-tier cases. Shared fixtures retain their original paths."""
from __future__ import annotations

import test_app_server as _support
from test_app_server import (
    Cancellation,
    Failure,
    asyncio,
    patch,
    time,
)


class AppServerTests(_support.AppServerTests):
    async def test_timeout_and_cancellation_include_blocked_stdin_drain(self) -> None:
        server = await self.start()
        blocked = asyncio.Event()
        with patch.object(server.child.stdin, "drain", side_effect=blocked.wait):
            before = time.monotonic()
            with self.assertRaises(Failure) as caught:
                await server.request("hang", {}, timeout=0.03)
            self.assertIn("request timeout", str(caught.exception))
            self.assertLess(time.monotonic() - before, 0.3)
        await server.close(force_at=time.monotonic() + 0.1)
        server = await self.start()
        cancellation = Cancellation()
        with patch.object(server.child.stdin, "drain", side_effect=blocked.wait):
            task = asyncio.create_task(server.request("hang", {}, cancellation=cancellation))
            await asyncio.sleep(0.02)
            cancellation.abort()
            with self.assertRaises(Failure):
                await asyncio.wait_for(task, 0.3)
