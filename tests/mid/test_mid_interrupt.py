"""Commented mid-tier selections; see MID_TIER.md before restoring a case."""

# Restore the needed imports and class header only for an explicit testing task.
# import test_interrupt as _support
# from test_interrupt import (
#     Failure,
#     FakeMapper,
#     FakeServer,
#     Interrupt,
#     Json,
#     Object,
#     asyncio,
#     unittest,
# )


# class Interrupt(_support.Interrupt):
# TEST-TIER-DISABLED-BEGIN tests/test_interrupt.py::Interrupt.test_the_tool_is_asked_once_even_after_the_grace
#     async def test_the_tool_is_asked_once_even_after_the_grace(self) -> None:
#         for deadline in (time.monotonic() - 1, time.monotonic() + 0.05):
#             with self.subTest(late=deadline < time.monotonic()):
#                 server = FakeServer()
#                 await interrupt_turns(cast(AppServer, server), cast(RunEvents, FakeMapper()), deadline)
#                 self.assertEqual(server.requests, [("turn/interrupt", {"threadId": "thread", "turnId": "turn"})])
# TEST-TIER-DISABLED-END tests/test_interrupt.py::Interrupt.test_the_tool_is_asked_once_even_after_the_grace


# Original deferred imports (restore at the required scope, never blindly at the tail).
# TEST-TIER-IMPORTS-BEGIN tests/test_interrupt.py:4
# import time
# TEST-TIER-IMPORTS-END tests/test_interrupt.py:4

# TEST-TIER-IMPORTS-BEGIN tests/test_interrupt.py:6
# from typing import cast
# TEST-TIER-IMPORTS-END tests/test_interrupt.py:6

# TEST-TIER-IMPORTS-BEGIN tests/test_interrupt.py:8
# from arbol_codex_driver.app_server import AppServer
# TEST-TIER-IMPORTS-END tests/test_interrupt.py:8

# TEST-TIER-IMPORTS-BEGIN tests/test_interrupt.py:11
# from arbol_codex_driver.run import interrupt_turns
# TEST-TIER-IMPORTS-END tests/test_interrupt.py:11

# TEST-TIER-IMPORTS-BEGIN tests/test_interrupt.py:12
# from arbol_codex_driver.run_events import RunEvents
# TEST-TIER-IMPORTS-END tests/test_interrupt.py:12

raise RuntimeError("Mid-tier tests require an explicitly requested testing task; see MID_TIER.md.")
