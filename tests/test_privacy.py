# Shared fixtures; case bodies live in top/ and mid/. See TESTS.md.
"""Known transient private values never reach callers, even across chunks."""

__all__ = [
    "Capture", "EventStream", "Object", "Output", "cast", "loads",
]
import unittest
from typing import cast

from arbol_codex_driver.event_stream import EventStream, Output
from arbol_codex_driver.json_types import Object, loads


class Capture:
    def __init__(self) -> None:
        self.text = ""

    async def write(self, text: str) -> None:
        self.text += text


class EventPrivacy(unittest.IsolatedAsyncioTestCase):
    pass  # TEST-TIER-EMPTY-SUITE; helpers remain importable.


# Archived complete imports; restore needed names in their original scope, not at this file tail.
