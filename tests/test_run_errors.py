# Shared fixtures only; test bodies are in top/ and mid/. See TESTS.md.
import unittest

from arbol_codex_driver.json_types import Json, Object
from arbol_codex_driver.run_errors import classify_error
from arbol_codex_driver.run_events import RunEvents


class RunErrors(unittest.TestCase):
    def classify(self, info: Json, message: str = "The vendor failed.") -> Object:
        return classify_error({"message": message, "codexErrorInfo": info})


class RunErrorEvents(unittest.TestCase):
    def setUp(self) -> None:
        self.events: list[Object] = []
        self.mapper = RunEvents(
            "thread",
            "turn",
            "model",
            lambda type_, data: self.events.append({"type": type_, **data}),
            tool_version="0.159.2",
            secrets=("private-key",),
        )

    def notify(self, method: str, params: Object) -> None:
        self.mapper.consume(method, {"threadId": "thread", "turnId": "turn", **params})


# Archived complete imports; restore needed names in their original scope, not at this file tail.
