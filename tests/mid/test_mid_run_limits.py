"""Mid-tier selections. Write or run only in an explicitly requested testing task."""
from __future__ import annotations

import test_run_limits as _support
from test_run_limits import (Object ,RunLimits ,iso ,object_value ,write_json)


class RunUsageStorage(_support.RunUsageStorage):

# TEST-TIER-BEGIN tests/test_run_limits.py::RunUsageStorage.test_late_report_does_not_restore_account_or_overwrite_newer_usage
    async def test_late_report_does_not_restore_account_or_overwrite_newer_usage(self) -> None:
        limits = RunLimits(self.initial["lastUsage"])
        usage = limits.observe({"rateLimits": {"primary": {"usedPercent": 25}}}, iso(1200))
        newer: Object = {**self.initial, "lastUsage": {**object_value(self.initial["lastUsage"]), "fetchedAt": iso(1300)}}
        records: list[Object] = [newer, {**self.initial, "state": "signed_out"},
                                 {**self.initial, "checkedAt": iso(1300)},
                                 {**self.initial, "account": {"plan": "team"}}]
        for current in records:
            with self.subTest(current=current):
                write_json(self.subscriptions.file("test-account", "record.json"), current)
                await self.subscriptions.store_run_usage(self.initial, usage)
                self.assertEqual(self.subscriptions.record("test-account"), current)
        self.subscriptions.file("test-account", "record.json").unlink()
        await self.subscriptions.store_run_usage(self.initial, usage)
        self.assertFalse(self.subscriptions.file("test-account", "record.json").exists())
# TEST-TIER-END tests/test_run_limits.py::RunUsageStorage.test_late_report_does_not_restore_account_or_overwrite_newer_usage
