"""Mid-tier selections. Write or run only in an explicitly requested testing task."""
from __future__ import annotations

import test_interrupt as _support
from test_interrupt import (
    AppServer,
    Failure,
    FakeMapper,
    FakeServer,
    Interrupt,
    Json,
    Object,
    RunEvents,
    asyncio,
    cast,
    interrupt_turns,
    time,
    unittest,
)


class Interrupt(_support.Interrupt):
# TEST-TIER-BEGIN tests/test_interrupt.py::Interrupt.test_the_tool_is_asked_once_even_after_the_grace
    async def test_the_tool_is_asked_once_even_after_the_grace(self) -> None:
        for deadline in (time.monotonic() - 1, time.monotonic() + 0.05):
            with self.subTest(late=deadline < time.monotonic()):
                server = FakeServer()
                await interrupt_turns(cast(AppServer, server), cast(RunEvents, FakeMapper()), deadline)
                self.assertEqual(server.requests, [("turn/interrupt", {"threadId": "thread", "turnId": "turn"})])
# TEST-TIER-END tests/test_interrupt.py::Interrupt.test_the_tool_is_asked_once_even_after_the_grace
