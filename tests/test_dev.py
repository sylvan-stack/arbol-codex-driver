# Shared fixtures only; test bodies are in top/ and mid/. See TESTS.md.
import unittest

from test_lifecycle import Fixture

from arbol_codex_driver.cancellation import Cancellation
from arbol_codex_driver.state import State
from arbol_codex_driver.subscriptions import Subscriptions


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
