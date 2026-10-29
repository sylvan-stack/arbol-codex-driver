# Shared fixtures; case bodies live in top/ and mid/. See TESTS.md.
"""Exact DRV-6 lock and version-cache boundaries, without a vendor tool."""

from __future__ import annotations
import asyncio
import os
import shlex
from types import SimpleNamespace
from unittest.mock import patch

from arbol_codex_driver import state as state_module
from arbol_codex_driver.errors import Failure
from arbol_codex_driver.json_types import object_value
from arbol_codex_driver.state import State, owner_json, process_owner, read_json, write_json
from arbol_codex_driver.tool import inspect_tool


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
