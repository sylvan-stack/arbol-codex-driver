# Shared fixtures; case bodies live in top/ and mid/. See TESTS.md.
"""Tool envelopes from the stable schema and retained vendor observations."""

from arbol_codex_driver.errors import Failure
from arbol_codex_driver.json_types import Json, Object, utf8
from arbol_codex_driver.run_events import RESULT_LIMIT, RunEvents


import unittest
from typing import cast

from arbol_codex_driver.json_types import Json, Object
from arbol_codex_driver.run_events import RunEvents


class MapperTools(unittest.TestCase):
    def setUp(self) -> None:
        self.events: list[Object] = []
        self.mapper = RunEvents(
            "main", "main-turn", "model", lambda type_, data: self.events.append({"type": type_, **data})
        )

    def notify(self, method: str, data: Object, thread: str = "main", turn: str = "main-turn") -> None:
        self.mapper.consume(method, {"threadId": thread, "turnId": turn, **data})

    def item(self, method: str, item: Object, thread: str = "main", turn: str = "main-turn") -> None:
        self.notify(method, {"item": item}, thread, turn)

    def complete(self, thread: str = "main", turn: str = "main-turn", status: str = "completed") -> None:
        self.mapper.consume("turn/completed", {"threadId": thread, "turn": {"id": turn, "status": status}})

    def spawn(self, id_: str = "spawn", receivers: list[str] | None = None) -> None:
        item: Object = {
            "type": "collabAgentToolCall",
            "id": id_,
            "tool": "spawnAgent",
            "status": "inProgress",
            "receiverThreadIds": [],
        }
        self.item("item/started", item)
        self.item(
            "item/completed",
            {**item, "status": "completed", "receiverThreadIds": cast(list[Json], receivers or ["child"])},
        )


# Archived complete imports; restore needed names in their original scope, not at this file tail.
