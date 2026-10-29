# Shared fixtures; case bodies live in top/ and mid/. See TESTS.md.
import asyncio
from unittest.mock import patch

from arbol_codex_driver.app_server import DRIVER_CONFIG, AppServer
from arbol_codex_driver.errors import Failure
from arbol_codex_driver.json_types import Object, dumps
from arbol_codex_driver.owner_setup import (
    DiagnosticScrubber,
    diagnostic_values,
    owner_mcp_config,
    sanitize_diagnostic,
)

import shlex
import sys
import tempfile
import time
import unittest
from pathlib import Path

from arbol_codex_driver.app_server import AppServer
from arbol_codex_driver.owner_setup import (
    diagnostic_values,
    owner_mcp_config,
)

PRIVATE = "owner-mcp-private-key-123456789"
HEADER = "Bearer owner-mcp-private-header-987654321"
CONFIG = f'''
model = "owner-model-not-imported"
unrelated_date = 2026-10-07
unrelated_nan = nan
[features]
memories = true
[mcp_servers."stdio.server"]
command = "/usr/bin/python3"
args = ["-m", "owner_module"]
enabled = false
startup_timeout_sec = 3.25
unknown_integer = 9223372036854775807
[mcp_servers."stdio.server".env]
API_KEY = "{PRIVATE}"
[mcp_servers.http]
url = "https://fixture.invalid/mcp"
bearer_token_env_var = "OWNER_MCP_TOKEN"
env_vars = ["OWNER_MCP_TOKEN"]
[mcp_servers.http.http_headers]
Authorization = "{HEADER}"
[mcp_servers.http.env_http_headers]
X-Owner = "OWNER_HEADER"
'''


class OwnerSetup(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="codex-owner-python-")
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        self.owner = self.folder / "owner"
        self.owner.mkdir()
        self.config = self.owner / ".codex" / "config.toml"
        self.config.parent.mkdir()
        self.env = {"HOME": str(self.owner), "CODEX_HOME": str(self.folder / "ignore-this-home")}


FAKE = r'''
import json, os, sys, time
PRIVATE = "owner-mcp-private-key-123456789"
HEADER = "Bearer owner-mcp-private-header-987654321"
def send(value):
    print(json.dumps(value), flush=True)
for line in sys.stdin:
    request = json.loads(line)
    method, id_ = request.get('method'), request.get('id')
    if method == 'initialized':
        continue
    if method == 'initialize':
        result = {'codexHome': os.environ['CODEX_HOME'], 'userAgent': 'codex/0.159.2 (Mac OS)'}
    elif method == 'config/read':
        result = {'config': {'check_for_update_on_startup': False, 'web_search': 'live', 'cli_auth_credentials_store': 'file', 'analytics': {'enabled': False}, 'features': {'memories': False}}}
    elif method in ('thread/start', 'thread/resume'):
        result = request['params']['config']
    elif method == 'fixture/tool':
        send({'method': 'item/completed', 'params': {'aggregateOutput': PRIVATE, 'input': HEADER}})
        result = {'ok': True}
    elif method == 'fixture/error':
        send({'id': id_, 'error': {'code': -32600, 'message': 'Bad MCP key ' + PRIVATE + ' and ' + HEADER}})
        continue
    elif method == 'fixture/stderr':
        for text in ('before ' + PRIVATE[:9], PRIVATE[9:23], PRIVATE[23:] + ' ' + HEADER + ' after'):
            sys.stderr.write(text)
            sys.stderr.flush()
            time.sleep(.02)
        sys.exit(3)
    else:
        result = {'ok': True}
    send({'id': id_, 'result': result})
'''


class OwnerDiagnostics(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="codex-owner-rpc-python-")
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        self.owner = self.folder / "owner"
        self.owner.mkdir()
        (self.owner / ".codex").mkdir()
        (self.owner / ".codex" / "config.toml").write_text(CONFIG)
        self.config = owner_mcp_config({"HOME": str(self.owner)})
        self.home = self.folder / "subscription-home"
        script = self.folder / "fixture.py"
        script.write_text(FAKE)
        program = self.folder / "codex"
        program.write_text(f"#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(str(script))}\n")
        program.chmod(0o700)
        self.server = await AppServer.start(
            tool_path=str(program),
            home=self.home,
            env={"HOME": str(self.owner), "PATH": "/usr/bin:/bin"},
            private_values=diagnostic_values(self.config),
            request_timeout=1,
        )

    async def asyncTearDown(self) -> None:
        await self.server.close(force_at=time.monotonic() + 0.1)


# Archived complete imports; restore needed names in their original scope, not at this file tail.
