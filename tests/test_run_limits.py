# Shared fixtures; case bodies live in top/ and mid/. See TESTS.md.
from typing import cast

from arbol_codex_driver.errors import Failure
from arbol_codex_driver.json_types import Json, Object, iso, object_value
from arbol_codex_driver.run_limits import RunLimits, exhausted_window_wait
from arbol_codex_driver.subscriptions import Subscriptions, parse_record

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


# Archived complete imports; restore needed names in their original scope, not at this file tail.
