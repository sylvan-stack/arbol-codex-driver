# Shared fixtures only; test bodies are in top/ and mid/. See TESTS.md.
"""Known transient private values never reach callers, even across chunks."""

import unittest


class Capture:
    def __init__(self) -> None:
        self.text = ""

    async def write(self, text: str) -> None:
        self.text += text


class EventPrivacy(unittest.IsolatedAsyncioTestCase):
    pass  # TEST-TIER-EMPTY-SUITE; helpers remain importable.



# Archived complete imports; restore needed names in their original scope, not at this file tail.
