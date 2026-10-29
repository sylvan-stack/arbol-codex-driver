# Shared fixtures; case bodies live in top/ and mid/. See TESTS.md.
"""Whole-process error and clock races through the credential-free vendor."""
import asyncio
import time
from typing import cast

from test_lifecycle import Fixture, ReaderTransport, Running
from arbol_codex_driver.json_types import Object, dumps, loads, object_value
from arbol_codex_driver.state import owner_alive, process_owner


from test_lifecycle import Fixture

from arbol_codex_driver.json_types import Object, loads, object_value


class ErrorRuns(Fixture):


    def assert_attention(self, final: Object) -> None:
        subscription = object_value(loads((self.state / "subscriptions/chatgpt/record.json").read_text()))
        self.assertEqual(subscription["state"], "needs_attention")
        self.assertEqual(subscription["problem"], final["error"])


# Archived complete imports; restore needed names in their original scope, not at this file tail.
