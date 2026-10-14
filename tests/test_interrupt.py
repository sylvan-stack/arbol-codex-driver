"""Stopping asks the tool first (DRV-2.16), even when the Driver gets there after the grace has passed."""

import asyncio
import time
import unittest
from typing import cast

from arbol_codex_driver.app_server import AppServer
from arbol_codex_driver.errors import Failure
from arbol_codex_driver.json_types import Json, Object
from arbol_codex_driver.run import interrupt_turns
from arbol_codex_driver.run_events import RunEvents


class FakeServer:
    def __init__(self) -> None:
        self.requests: list[tuple[str, Json]] = []

    def take_notifications(self) -> list[object]:
        return []

    async def request(self, method: str, params: Json, *, timeout: float | None = None) -> Json:
        self.requests.append((method, params))
        await asyncio.sleep(10)
        return None

    async def next_notification(self, *, timeout: float | None = None) -> object:
        await asyncio.sleep(timeout or 0)
        raise Failure("tool_failed", "Timed out.")


class FakeMapper:
    has_active_agents = False

    @property
    def active_turns(self) -> list[Object]:
        return [{"threadId": "thread", "turnId": "turn"}]

    def consume(self, method: str, params: Json) -> None:
        pass


class Interrupt(unittest.IsolatedAsyncioTestCase):
    async def test_the_tool_is_asked_once_even_after_the_grace(self) -> None:
        for deadline in (time.monotonic() - 1, time.monotonic() + 0.05):
            with self.subTest(late=deadline < time.monotonic()):
                server = FakeServer()
                await interrupt_turns(cast(AppServer, server), cast(RunEvents, FakeMapper()), deadline)
                self.assertEqual(server.requests, [("turn/interrupt", {"threadId": "thread", "turnId": "turn"})])


if __name__ == "__main__":
    unittest.main()
