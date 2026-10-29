# Shared fixtures; case bodies live in top/ and mid/. See TESTS.md.
import asyncio
import os
import time
from typing import cast

from test_lifecycle import ENTRY, Fixture
from arbol_codex_driver.continuity import digest
from arbol_codex_driver.json_types import Json, Object, dumps, iso, loads, now, object_value
from arbol_codex_driver.state import owner_json, parse_owner, process_owner, write_json


from test_lifecycle import Fixture

from arbol_codex_driver.json_types import Json, Object, dumps, loads, object_value


class Accounts(Fixture):
    pass  # TEST-TIER-EMPTY-SUITE; helpers remain importable.


class Continuity(Fixture):
    async def request_run(self, fields: Object, part: str = "plain", outcome: str = "completed") -> list[Object]:
        self.scenario("C14 " + part)
        path = self.home / "request.json"
        path.write_text(
            dumps(
                {
                    "runId": "continuity",
                    "chatSessionId": "opaque/../chat",
                    "workingDirectory": str(self.home),
                    "tools": "none",
                    "history": [],
                    "input": {"role": "user", "text": "hello"},
                    **fields,
                }
            )
        )
        code, output, error = await self.invoke(["run", "--request", str(path)])
        self.assertEqual((code, error), (0 if outcome == "completed" else 1, b""))
        events = [object_value(loads(raw)) for raw in output.decode().splitlines()]
        self.assertEqual(events[-1]["outcome"], outcome)
        self.assertEqual(sum(event["type"] == "finished" for event in events), 1)
        self.assertEqual([event["seq"] for event in events], list(range(1, len(events) + 1)))
        return events

    def history(self, input_: Object, events: list[Object], prior: list[Json] | None = None) -> list[Json]:
        return [
            *(prior or []),
            {"type": "message", **input_},
            *(
                {"type": "message", "role": "assistant", "text": event["text"]}
                for event in events
                if event["type"] == "text" and "parentCallId" not in event
            ),
        ]


# Archived complete imports; restore needed names in their original scope, not at this file tail.
