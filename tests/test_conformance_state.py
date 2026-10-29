# Shared fixtures only; test bodies are in top/ and mid/. See TESTS.md.
"""Exact DRV-6 lock and version-cache boundaries, without a vendor tool."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from arbol_codex_driver.state import State


class LockClock:
    def __init__(self) -> None:
        self.elapsed = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.elapsed

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.elapsed += seconds


class ConformanceState(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="codex-conformance-state-")
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.state = State(self.folder / "state")
        self.state.initialize()



# Archived complete imports; restore needed names in their original scope, not at this file tail.
