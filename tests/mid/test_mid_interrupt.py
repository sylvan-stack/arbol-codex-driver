
# LOW TIER — DO NOT ENABLE OR RECREATE
# Historical examples only. Read before adding related tests; never execute.
# LOW-TIER-BEGIN: tests/mid/test_mid_interrupt.py::Interrupt.test_the_tool_is_asked_once_even_after_the_grace
# Reason: Records a request on a fake server for an already-expired/live deadline. The retained real lifecycle cases verify interrupt-once and shutdown behavior across actual processes. Case reviewed: The tool is asked once even after the grace.
# Source: arbol-codex-driver@0c596c5960c34039bd48d05df9b66b4ea9f31680:tests/mid/test_mid_interrupt.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_the_tool_is_asked_once_even_after_the_grace(self) -> None:
#         for deadline in (time.monotonic() - 1, time.monotonic() + 0.05):
#             with self.subTest(late=deadline < time.monotonic()):
#                 server = FakeServer()
#                 await interrupt_turns(cast(AppServer, server), cast(RunEvents, FakeMapper()), deadline)
#                 self.assertEqual(server.requests, [("turn/interrupt", {"threadId": "thread", "turnId": "turn"})])
# LOW-TIER-SOURCE-END
# LOW-TIER-END
