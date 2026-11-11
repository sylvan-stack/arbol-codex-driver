__all__ = [
    "Failure", "Path", "RESULT_LIMIT", "cast", "dumps", "object_value", "plain_command", "read_run_request",
    "tempfile", "truncate_result", "utf8",
]
# Shared fixtures; case bodies live in top/ and mid/. See TESTS.md.
import tempfile
import unittest
from pathlib import Path
from typing import cast

from arbol_codex_driver.errors import Failure
from arbol_codex_driver.json_types import Json, Object, dumps, object_value, utf8
from arbol_codex_driver.run_events import RESULT_LIMIT, RunEvents, plain_command, truncate_result
from arbol_codex_driver.run_request import read_run_request


class Requests(unittest.IsolatedAsyncioTestCase):
    pass  # TEST-TIER-EMPTY-SUITE; helpers remain importable.


class Mapper(unittest.TestCase):
    def setUp(self) -> None:
        self.events: list[Object] = []
        self.mapper = RunEvents(
            "thread", "turn", "model", lambda type_, data: self.events.append({"type": type_, **data})
        )

    def notify(self, method: str, data: Object) -> None:
        self.mapper.consume(method, {"threadId": "thread", "turnId": "turn", **data})

    def item(self, method: str, item: Object) -> None:
        self.notify(method, {"item": item})

    def complete(self, status: str = "completed", error: Json = None) -> None:
        self.mapper.consume(
            "turn/completed", {"threadId": "thread", "turn": {"id": "turn", "status": status, "error": error}}
        )


# Archived complete imports; restore needed names in their original scope, not at this file tail.
