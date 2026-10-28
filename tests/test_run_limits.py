import tempfile
import unittest
from pathlib import Path

from arbol_codex_driver.catalog import normalize_usage
from arbol_codex_driver.json_types import Object, iso
from arbol_codex_driver.state import State, write_json
from arbol_codex_driver.subscriptions import Subscriptions


def snapshot() -> Object:
    limits: Object = {
        "limitId": "codex",
        "planType": "pro",
        "primary": {"usedPercent": 10, "windowDurationMins": 300, "resetsAt": 2000},
        "secondary": {"usedPercent": 95, "windowDurationMins": 10080, "resetsAt": 3000},
        "rateLimitReachedType": "weekly",
        "spendControlReached": False,
        "credits": {"hasCredits": True, "balance": "5"},
    }
    return {"rateLimits": limits, "rateLimitsByLimitId": {"codex": limits}, "ordinaryUsageAllowed": True}


class RunUsage(unittest.TestCase):
    pass  # TEST-TIER-EMPTY-SUITE; helpers remain importable.
# TEST-TIER-DISABLED-BEGIN tests/test_run_limits.py::RunUsage.test_sparse_notifications_preserve_stored_fields_and_latest_values
#     def test_sparse_notifications_preserve_stored_fields_and_latest_values(self) -> None:
#         previous = normalize_usage(snapshot(), fetched_at=iso(1000))
#         limits = RunLimits(previous)
#         self.assertIsNone(limits.report)
#         limits.observe({"rateLimits": {"primary": {"usedPercent": 20}, "rateLimitReachedType": None,
#                                       "spendControlReached": None}}, iso(1100))
#         latest = limits.observe({"rateLimits": {"primary": {"usedPercent": 25},
#                                                 "secondary": {"usedPercent": 100}}}, iso(1200))
#         self.assertEqual([object_value(item)["usedPercent"] for item in cast(list[Json], latest["windows"])], [25, 100])
#         self.assertEqual([object_value(item)["windowMinutes"] for item in cast(list[Json], latest["windows"])], [300, 10080])
#         self.assertEqual([object_value(item)["resetsAt"] for item in cast(list[Json], latest["windows"])], [iso(2000), iso(3000)])
#         self.assertEqual(object_value(latest["extra"])["rateLimitReachedType"], "weekly")
#         self.assertIs(object_value(latest["extra"])["spendControlReached"], False)
#         self.assertEqual(object_value(object_value(latest["extra"])["credits"])["balance"], "5")
#         self.assertEqual(latest["fetchedAt"], iso(1200))
#         raw = object_value(object_value(object_value(latest["extra"])["rateLimitsByLimitId"])["codex"])
#         self.assertEqual(object_value(raw["primary"])["usedPercent"], 25)
#         self.assertEqual(object_value(object_value(previous["extra"])["credits"])["balance"], "5")
# TEST-TIER-DISABLED-END tests/test_run_limits.py::RunUsage.test_sparse_notifications_preserve_stored_fields_and_latest_values

# TEST-TIER-DISABLED-BEGIN tests/test_run_limits.py::RunUsage.test_window_kind_comes_from_duration_and_by_id_updates_work
#     def test_window_kind_comes_from_duration_and_by_id_updates_work(self) -> None:
#         limits = RunLimits(fallback_plan="pro")
#         latest = limits.observe({"rateLimitsByLimitId": {"codex": {
#             "primary": {"usedPercent": 60, "windowDurationMins": 10080},
#             "secondary": {"usedPercent": 30, "windowDurationMins": 300}}}}, iso(1000))
#         self.assertEqual([object_value(item)["kind"] for item in cast(list[Json], latest["windows"])], ["weekly", "session"])
#         self.assertEqual(latest["plan"], "pro")
#         latest = limits.observe({"rateLimitsByLimitId": {"codex": {"primary": {"usedPercent": 61}}}}, iso(1001))
#         self.assertEqual(object_value(cast(list[Json], latest["windows"])[0])["usedPercent"], 61)
# TEST-TIER-DISABLED-END tests/test_run_limits.py::RunUsage.test_window_kind_comes_from_duration_and_by_id_updates_work

# TEST-TIER-DISABLED-BEGIN tests/test_run_limits.py::RunUsage.test_malformed_update_keeps_last_good_report
#     def test_malformed_update_keeps_last_good_report(self) -> None:
#         limits = RunLimits()
#         limits.observe(snapshot(), iso(1000))
#         previous = limits.report
#         for raw in ({}, {"rateLimits": {"primary": {"usedPercent": "private-malformed"}}}):
#             with self.subTest(raw=raw), self.assertRaises(Failure):
#                 limits.observe(cast(Json, raw), iso(1001))
#             self.assertEqual(limits.report, previous)
# TEST-TIER-DISABLED-END tests/test_run_limits.py::RunUsage.test_malformed_update_keeps_last_good_report

# TEST-TIER-DISABLED-BEGIN tests/test_run_limits.py::RunUsage.test_wait_requires_current_vendor_exhaustion_and_reset_without_cache_guessing
#     def test_wait_requires_current_vendor_exhaustion_and_reset_without_cache_guessing(self) -> None:
#         limits = RunLimits(normalize_usage(snapshot(), fetched_at=iso(1000)))
#         limits.observe({"rateLimits": {"secondary": {"usedPercent": 100}}}, iso(1100))
#         self.assertIsNone(limits.wait_seconds(1200))
#         limits.observe_read({"rateLimits": {"secondary": {"usedPercent": 100}}}, iso(1200))
#         self.assertIsNone(limits.wait_seconds(1200))
#         raw: Object = {"rateLimits": {
#             "primary": {"usedPercent": 99, "resetsAt": 9999},
#             "secondary": {"usedPercent": 100, "resetsAt": 1300}}}
#         limits.observe_read(raw, iso(1200))
#         self.assertEqual(limits.wait_seconds(1200.5), 99.5)
#         self.assertEqual(limits.wait_seconds(1400), 0)
#         self.assertIsNone(exhausted_window_wait({"rateLimits": {"primary": {"resetsAt": 3000}}}, 1200))
#         self.assertEqual(exhausted_window_wait({"rateLimitsByLimitId": {"codex": {
#             "primary": {"usedPercent": 100, "resetsAt": 1500},
#             "secondary": {"usedPercent": 100, "resetsAt": 1600}}}}, 1200), 400)
# TEST-TIER-DISABLED-END tests/test_run_limits.py::RunUsage.test_wait_requires_current_vendor_exhaustion_and_reset_without_cache_guessing


class RunUsageStorage(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="codex-run-usage-")
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        state = State(self.folder / "state")
        state.initialize()
        self.subscriptions = Subscriptions(state, {}, [], self.folder / "settings.json", {})
        self.initial: Object = {
            "id": "test-account", "family": "chatgpt", "label": "Test", "auth": "vendor_login",
            "state": "signed_in", "account": {"plan": "pro"}, "createdAt": iso(900), "updatedAt": iso(1000),
            "checkedAt": iso(1000), "lastUsage": normalize_usage(snapshot(), fetched_at=iso(1000)),
        }
        write_json(self.subscriptions.file("test-account", "record.json"), self.initial)

# TEST-TIER-DISABLED-BEGIN tests/test_run_limits.py::RunUsageStorage.test_persist_preserves_concurrent_fields_and_compatible_record
#     async def test_persist_preserves_concurrent_fields_and_compatible_record(self) -> None:
#         limits = RunLimits(self.initial["lastUsage"])
#         usage = limits.observe({"rateLimits": {"primary": {"usedPercent": 25}}}, iso(1200))
#         current = {**self.initial, "label": "Renamed", "updatedAt": iso(1100)}
#         last = object_value(current["lastUsage"]).copy()
#         last["extra"] = {**object_value(last["extra"]), "ordinaryUsageAllowed": False,
#                          "credits": {"hasCredits": True, "balance": "4"}}
#         last["fetchedAt"] = iso(1100)
#         current["lastUsage"] = last
#         write_json(self.subscriptions.file("test-account", "record.json"), current)
#         await self.subscriptions.store_run_usage(self.initial, usage)
#         record = self.subscriptions.record("test-account")
#         self.assertEqual(parse_record(record, "test-account"), record)
#         self.assertEqual(record["label"], "Renamed")
#         stored = object_value(record["lastUsage"])
#         self.assertEqual(object_value(cast(list[Json], stored["windows"])[0])["usedPercent"], 25)
#         self.assertIs(object_value(stored["extra"])["ordinaryUsageAllowed"], False)
#         self.assertEqual(object_value(object_value(stored["extra"])["credits"])["balance"], "4")
#         self.assertEqual(self.subscriptions.file("test-account", "record.json").stat().st_mode & 0o777, 0o600)
# TEST-TIER-DISABLED-END tests/test_run_limits.py::RunUsageStorage.test_persist_preserves_concurrent_fields_and_compatible_record

# TEST-TIER-DISABLED-BEGIN tests/test_run_limits.py::RunUsageStorage.test_late_report_does_not_restore_account_or_overwrite_newer_usage
#     async def test_late_report_does_not_restore_account_or_overwrite_newer_usage(self) -> None:
#         limits = RunLimits(self.initial["lastUsage"])
#         usage = limits.observe({"rateLimits": {"primary": {"usedPercent": 25}}}, iso(1200))
#         newer: Object = {**self.initial, "lastUsage": {**object_value(self.initial["lastUsage"]), "fetchedAt": iso(1300)}}
#         records: list[Object] = [newer, {**self.initial, "state": "signed_out"},
#                                  {**self.initial, "checkedAt": iso(1300)},
#                                  {**self.initial, "account": {"plan": "team"}}]
#         for current in records:
#             with self.subTest(current=current):
#                 write_json(self.subscriptions.file("test-account", "record.json"), current)
#                 await self.subscriptions.store_run_usage(self.initial, usage)
#                 self.assertEqual(self.subscriptions.record("test-account"), current)
#         self.subscriptions.file("test-account", "record.json").unlink()
#         await self.subscriptions.store_run_usage(self.initial, usage)
#         self.assertFalse(self.subscriptions.file("test-account", "record.json").exists())
# TEST-TIER-DISABLED-END tests/test_run_limits.py::RunUsageStorage.test_late_report_does_not_restore_account_or_overwrite_newer_usage

# Archived complete imports; restore needed names in their original scope, not at this file tail.
# TEST-TIER-IMPORTS-BEGIN tests/test_run_limits.py:4
# from typing import cast
# TEST-TIER-IMPORTS-END tests/test_run_limits.py:4
# TEST-TIER-IMPORTS-BEGIN tests/test_run_limits.py:7
# from arbol_codex_driver.errors import Failure
# TEST-TIER-IMPORTS-END tests/test_run_limits.py:7
# TEST-TIER-IMPORTS-BEGIN tests/test_run_limits.py:8
# from arbol_codex_driver.json_types import Json, Object, iso, object_value
# TEST-TIER-IMPORTS-END tests/test_run_limits.py:8
# TEST-TIER-IMPORTS-BEGIN tests/test_run_limits.py:9
# from arbol_codex_driver.run_limits import RunLimits, exhausted_window_wait
# TEST-TIER-IMPORTS-END tests/test_run_limits.py:9
# TEST-TIER-IMPORTS-BEGIN tests/test_run_limits.py:11
# from arbol_codex_driver.subscriptions import Subscriptions, parse_record
# TEST-TIER-IMPORTS-END tests/test_run_limits.py:11
