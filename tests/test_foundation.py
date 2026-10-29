# Shared fixtures only; test bodies are in top/ and mid/. See TESTS.md.
import tempfile
import unittest
from pathlib import Path

from arbol_codex_driver.state import (
    State,
)

ROOT = Path(__file__).resolve().parent.parent


class Foundation(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="codex-python-unit-")
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        self.state = State(self.folder / "state")
        self.state.initialize()


class FamilySettings(unittest.IsolatedAsyncioTestCase):
    pass  # TEST-TIER-EMPTY-SUITE; helpers remain importable.

# Archived complete imports; restore needed names in their original scope, not at this file tail.
