"""Stopping asks the tool first (DRV-2.16), even when the Driver gets there after the grace has passed."""

import asyncio
import unittest

from arbol_codex_driver.errors import Failure
from arbol_codex_driver.json_types import Json, Object


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
    pass  # TEST-TIER-EMPTY-SUITE; helpers remain importable.
# TEST-TIER-DISABLED-BEGIN tests/test_interrupt.py::Interrupt.test_the_tool_is_asked_once_even_after_the_grace
#     async def test_the_tool_is_asked_once_even_after_the_grace(self) -> None:
#         for deadline in (time.monotonic() - 1, time.monotonic() + 0.05):
#             with self.subTest(late=deadline < time.monotonic()):
#                 server = FakeServer()
#                 await interrupt_turns(cast(AppServer, server), cast(RunEvents, FakeMapper()), deadline)
#                 self.assertEqual(server.requests, [("turn/interrupt", {"threadId": "thread", "turnId": "turn"})])
# TEST-TIER-DISABLED-END tests/test_interrupt.py::Interrupt.test_the_tool_is_asked_once_even_after_the_grace


if __name__ == "__main__":
    unittest.main()

# Archived complete imports; restore needed names in their original scope, not at this file tail.
# TEST-TIER-IMPORTS-BEGIN tests/test_interrupt.py:4
# import time
# TEST-TIER-IMPORTS-END tests/test_interrupt.py:4
# TEST-TIER-IMPORTS-BEGIN tests/test_interrupt.py:6
# from typing import cast
# TEST-TIER-IMPORTS-END tests/test_interrupt.py:6
# TEST-TIER-IMPORTS-BEGIN tests/test_interrupt.py:8
# from arbol_codex_driver.app_server import AppServer
# TEST-TIER-IMPORTS-END tests/test_interrupt.py:8
# TEST-TIER-IMPORTS-BEGIN tests/test_interrupt.py:11
# from arbol_codex_driver.run import interrupt_turns
# TEST-TIER-IMPORTS-END tests/test_interrupt.py:11
# TEST-TIER-IMPORTS-BEGIN tests/test_interrupt.py:12
# from arbol_codex_driver.run_events import RunEvents
# TEST-TIER-IMPORTS-END tests/test_interrupt.py:12
