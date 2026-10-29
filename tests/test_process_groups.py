# Shared fixtures only; test bodies are in top/ and mid/. See TESTS.md.
"""Process-table identity checks protect unrelated processes during cleanup."""

from __future__ import annotations

import time
import unittest
from unittest.mock import AsyncMock, patch

from arbol_codex_driver.json_types import iso
from arbol_codex_driver.process_groups import (
    ProcessSnapshot,
    force_process_groups,
)
from arbol_codex_driver.state import Owner


def owner(pid: int, started: float = 1000) -> Owner:
    return {"pid": pid, "startedAt": iso(started)}


def row(pid: int, group: int, parent: int = 1, started: float = 1000, zombie: bool = False) -> ProcessSnapshot:
    return {"pid": pid, "startedAt": iso(started), "parentId": parent, "groupId": group, "zombie": zombie}


class ProcessGroupTests(unittest.TestCase):
    pass  # TEST-TIER-EMPTY-SUITE; helpers remain importable.


class ForcedProcessGroupTests(unittest.IsolatedAsyncioTestCase):
    pass  # Shared fixture base; case bodies live in top/ and mid/.



# Archived complete imports; restore needed names in their original scope, not at this file tail.
