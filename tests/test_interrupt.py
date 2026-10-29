# Shared fixtures only; test bodies are in top/ and mid/. See TESTS.md.
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



# Archived complete imports; restore needed names in their original scope, not at this file tail.
