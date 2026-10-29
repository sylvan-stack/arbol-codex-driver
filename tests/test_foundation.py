# Shared fixtures; case bodies live in top/ and mid/. See TESTS.md.
import asyncio
import os
import time
from dataclasses import replace
from typing import cast

from arbol_codex_driver.arguments import parse_arguments
from arbol_codex_driver.build import build_identity
from arbol_codex_driver.catalog import (
    builtin_catalog,
    normalize_account,
    normalize_models,
    normalize_usage,
    read_model_catalog,
)
from arbol_codex_driver.continuity import Chats, MessageDigest, digest, message_digest, saved_conversation
from arbol_codex_driver.environment import clean_environment
from arbol_codex_driver.errors import Failure, safe_failure
from arbol_codex_driver.history import history_items, labelled_history_input, prepare_turn_input
from arbol_codex_driver.json_types import Json, Object, dumps, loads, now, object_value, utf8
from arbol_codex_driver.run_request import read_run_request
from arbol_codex_driver.runs import Runs
from arbol_codex_driver.settings import read_settings
from arbol_codex_driver.state import (
    State,
    atomic_write,
    fixed_wait,
    owner_alive,
    owner_json,
    parse_owner,
    process_owner,
    read_json,
    write_json,
)
from arbol_codex_driver.subscriptions import Subscriptions

import tempfile
import unittest
from pathlib import Path

from arbol_codex_driver.state import (
    State,
)

ROOT = Path(__file__).resolve().parent.parent


class Foundation(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="codex-python-unit-")
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        self.state = State(self.folder / "state")
        self.state.initialize()


class FamilySettings(unittest.IsolatedAsyncioTestCase):
    pass  # TEST-TIER-EMPTY-SUITE; helpers remain importable.

# Archived complete imports; restore needed names in their original scope, not at this file tail.
