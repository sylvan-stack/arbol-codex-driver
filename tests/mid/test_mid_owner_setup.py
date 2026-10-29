"""Mid-tier selections. Write or run only in an explicitly requested testing task."""
from __future__ import annotations

import test_owner_setup as _support
from test_owner_setup import (Failure ,HEADER ,PRIVATE ,asyncio ,dumps)


class OwnerDiagnostics(_support.OwnerDiagnostics):

# TEST-TIER-BEGIN tests/test_owner_setup.py::OwnerDiagnostics.test_echoed_setup_errors_are_private_and_tool_payloads_are_unchanged
    async def test_echoed_setup_errors_are_private_and_tool_payloads_are_unchanged(self) -> None:
        with self.assertRaises(Failure) as caught:
            await self.server.request("fixture/error", {})
        error = dumps(caught.exception.result)
        self.assertNotIn(PRIVATE, error)
        self.assertNotIn(HEADER, error)
        self.assertIn("[redacted]", error)
        await self.server.request("fixture/tool", {})
        notice = await self.server.next_notification()
        self.assertEqual(notice.params, {"aggregateOutput": PRIVATE, "input": HEADER})
# TEST-TIER-END tests/test_owner_setup.py::OwnerDiagnostics.test_echoed_setup_errors_are_private_and_tool_payloads_are_unchanged

# TEST-TIER-BEGIN tests/test_owner_setup.py::OwnerDiagnostics.test_split_stderr_values_are_never_retained_or_reported
    async def test_split_stderr_values_are_never_retained_or_reported(self) -> None:
        with self.assertRaises(Failure) as caught:
            await self.server.request("fixture/stderr", {})
        await asyncio.gather(self.server.tasks[1], return_exceptions=True)
        self.assertNotIn(PRIVATE, self.server.log_tail)
        self.assertNotIn(HEADER, self.server.log_tail)
        self.assertIn("before [redacted] [redacted] after", self.server.log_tail)
        self.assertNotIn(PRIVATE, dumps(caught.exception.result))
        self.assertNotIn(HEADER, dumps(caught.exception.result))
# TEST-TIER-END tests/test_owner_setup.py::OwnerDiagnostics.test_split_stderr_values_are_never_retained_or_reported
