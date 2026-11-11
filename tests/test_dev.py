__all__ = [
    "AppServer", "AsyncMock", "Cancellation", "Coroutine", "Failure", "Json", "OLDEST_SUPPORTED", "Object", "Path",
    "READY", "asyncio", "cast", "check_account", "command", "dumps", "execute_run", "live_check", "loads", "now",
    "object_value", "patch", "probe", "probe_shape", "read_json", "refuse_exhausted", "select_model", "stop_child",
    "sys", "usage_change", "write_json",
]
# Shared fixtures; case bodies live in top/ and mid/. See TESTS.md.
import asyncio
import sys
import unittest
from collections.abc import Coroutine
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, patch

from test_lifecycle import Fixture

from arbol_codex_driver.app_server import AppServer
from arbol_codex_driver.cancellation import Cancellation
from arbol_codex_driver.dev import check_account, execute_run, live_check, probe, select_model
from arbol_codex_driver.dev_support import READY, command, probe_shape, refuse_exhausted, stop_child, usage_change
from arbol_codex_driver.errors import Failure
from arbol_codex_driver.json_types import Json, Object, dumps, loads, now, object_value
from arbol_codex_driver.state import State, read_json, write_json
from arbol_codex_driver.subscriptions import Subscriptions
from arbol_codex_driver.tool import OLDEST_SUPPORTED


class DevShapes(unittest.TestCase):
    pass  # TEST-TIER-EMPTY-SUITE; helpers remain importable.


class DevChecks(Fixture):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.assertEqual(
            (
                await self.invoke(
                    ["subscriptions", "create", "--family", "chatgpt", "--label", "Tests", "--id", "test-chatgpt"]
                )
            )[0],
            0,
        )
        self.assertEqual((await self.invoke(["subscriptions", "sign-in", "test-chatgpt"]))[0], 0)
        self.scenario("C32 plain")
        state = State(str(self.state))
        state.initialize()
        self.subscriptions = Subscriptions(
            state,
            {"toolPath": str(self.tool / "codex")},
            [],
            self.home / ".arbol/arbol-codex-driver.json",
            self.env,
            Cancellation(),
        )


# Archived complete imports; restore needed names in their original scope, not at this file tail.
