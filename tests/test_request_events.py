# Shared fixtures only; test bodies are in top/ and mid/. See TESTS.md.
import unittest

from arbol_codex_driver.json_types import Json, Object
from arbol_codex_driver.run_events import RunEvents


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
