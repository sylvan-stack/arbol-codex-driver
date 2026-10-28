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

# TEST-TIER-DISABLED-BEGIN tests/test_owner_setup.py::OwnerSetup.test_preserves_mcp_tables_and_reads_no_other_owner_file
#     def test_preserves_mcp_tables_and_reads_no_other_owner_file(self) -> None:
#         self.config.write_text(CONFIG)
#         (self.config.parent / "auth.json").write_text("owner-login-never-read")
#         (self.config.parent / "AGENTS.md").write_text("owner-instructions-never-imported")
#         skills = self.owner / ".agents" / "skills" / "fixture"
#         skills.mkdir(parents=True)
#         (skills / "SKILL.md").write_text("owner-skill-discovered-by-codex")
#         before = {
#             path: (path.read_bytes(), path.stat().st_mtime_ns, path.stat().st_mode)
#             for path in self.owner.rglob("*")
#             if path.is_file()
#         }
#         expected = {
#             "mcp_servers": {
#                 "stdio.server": {
#                     "command": "/usr/bin/python3",
#                     "args": ["-m", "owner_module"],
#                     "enabled": False,
#                     "startup_timeout_sec": 3.25,
#                     "unknown_integer": 9223372036854775807,
#                     "env": {"API_KEY": PRIVATE},
#                 },
#                 "http": {
#                     "url": "https://fixture.invalid/mcp",
#                     "bearer_token_env_var": "OWNER_MCP_TOKEN",
#                     "env_vars": ["OWNER_MCP_TOKEN"],
#                     "http_headers": {"Authorization": HEADER},
#                     "env_http_headers": {"X-Owner": "OWNER_HEADER"},
#                 },
#             }
#         }
#         original = Path.open
#         accessed: list[Path] = []
#
#         def opened(path: Path, mode: str = "r") -> object:
#             accessed.append(path)
#             return original(path, mode)
#
#         with patch.object(Path, "open", new=opened):
#             actual = owner_mcp_config(self.env)
#         self.assertEqual(actual, expected)
#         self.assertEqual(accessed, [self.config])
#         self.assertEqual(
#             before,
#             {
#                 path: (path.read_bytes(), path.stat().st_mtime_ns, path.stat().st_mode)
#                 for path in self.owner.rglob("*")
#                 if path.is_file()
#             },
#         )
# TEST-TIER-DISABLED-END tests/test_owner_setup.py::OwnerSetup.test_preserves_mcp_tables_and_reads_no_other_owner_file

# TEST-TIER-DISABLED-BEGIN tests/test_owner_setup.py::OwnerSetup.test_missing_tables_empty_table_and_each_run_reads_current_owner_home
#     def test_missing_tables_empty_table_and_each_run_reads_current_owner_home(self) -> None:
#         self.assertEqual(owner_mcp_config(self.env), {})
#         self.config.write_text('model = "not-imported"\n')
#         self.assertEqual(owner_mcp_config(self.env), {})
#         self.config.write_text("[mcp_servers]\n")
#         self.assertEqual(owner_mcp_config(self.env), {"mcp_servers": {}})
#         self.config.write_text('[mcp_servers.changed]\ncommand = "fixture-new-command"\n')
#         self.assertEqual(
#             owner_mcp_config(self.env), {"mcp_servers": {"changed": {"command": "fixture-new-command"}}}
#         )
#         with patch.object(Path, "home", return_value=self.owner):
#             self.assertEqual(owner_mcp_config({}), owner_mcp_config(self.env))
# TEST-TIER-DISABLED-END tests/test_owner_setup.py::OwnerSetup.test_missing_tables_empty_table_and_each_run_reads_current_owner_home

# TEST-TIER-DISABLED-BEGIN tests/test_owner_setup.py::OwnerSetup.test_malformed_unreadable_and_non_json_tables_have_nonsecret_errors
#     def test_malformed_unreadable_and_non_json_tables_have_nonsecret_errors(self) -> None:
#         for source in (
#             f'broken = "{PRIVATE}\n',
#             f'mcp_servers = "{PRIVATE}"\n',
#             f'mcp_servers = ["{PRIVATE}"]\n',
#             f'[mcp_servers.fixture]\nkey = "{PRIVATE}"\ndate = 2026-10-07\n',
#             f'[mcp_servers.fixture]\nkey = "{PRIVATE}"\nvalue = nan\n',
#             f'[mcp_servers.fixture]\nkey = "{PRIVATE}"\nvalue = +inf\n',
#         ):
#             with self.subTest(source=source):
#                 self.config.write_text(source)
#                 with self.assertRaises(Failure) as caught:
#                     owner_mcp_config(self.env)
#                 self.assertEqual(caught.exception.result["code"], "invalid_input")
#                 self.assertNotIn(PRIVATE, dumps(caught.exception.result))
#                 self.assertNotIn(str(self.owner), dumps(caught.exception.result))
#                 self.assertNotIn("detail", caught.exception.result)
#         with patch.object(Path, "open", side_effect=PermissionError(PRIVATE)), self.assertRaises(Failure) as caught:
#             owner_mcp_config(self.env)
#         self.assertEqual(caught.exception.result["code"], "invalid_input")
#         self.assertNotIn(PRIVATE, dumps(caught.exception.result))
# TEST-TIER-DISABLED-END tests/test_owner_setup.py::OwnerSetup.test_malformed_unreadable_and_non_json_tables_have_nonsecret_errors

# TEST-TIER-DISABLED-BEGIN tests/test_owner_setup.py::OwnerSetup.test_diagnostics_scrub_longest_literals_and_preserve_structured_fields
#     def test_diagnostics_scrub_longest_literals_and_preserve_structured_fields(self) -> None:
#         config: Object = {"mcp_servers": {"fixture": {"env": {"LONG": PRIVATE, "SHORT": "owner-mcp", "KEY": "code"}}}}
#         values = diagnostic_values(config)
#         self.assertEqual(set(values), {PRIVATE, "owner-mcp", "code"})
#         self.assertEqual(
#             sanitize_diagnostic({"code": "tool_failed", "message": PRIVATE, "nested": [f"prefix {PRIVATE}"]}, values),
#             {"code": "tool_failed", "message": "[redacted]", "nested": ["prefix [redacted]"]},
#         )
#         scrubber = DiagnosticScrubber((PRIVATE, "owner-mcp"))
#         pieces = ["before " + PRIVATE[:9], PRIVATE[9:23], PRIVATE[23:] + " after"]
#         self.assertEqual("".join(scrubber.feed(piece) for piece in pieces) + scrubber.feed("", final=True), "before [redacted] after")
#         self.assertEqual(scrubber.pending, "")
#         incomplete = DiagnosticScrubber((PRIVATE,))
#         self.assertEqual(incomplete.feed("before " + PRIVATE[:12]), "before ")
#         self.assertEqual(incomplete.feed("", final=True), "[redacted]")
# TEST-TIER-DISABLED-END tests/test_owner_setup.py::OwnerSetup.test_diagnostics_scrub_longest_literals_and_preserve_structured_fields


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

# TEST-TIER-DISABLED-BEGIN tests/test_owner_setup.py::OwnerDiagnostics.test_transient_owner_payload_keeps_exact_json_values_and_home_unmodified
#     async def test_transient_owner_payload_keeps_exact_json_values_and_home_unmodified(self) -> None:
#         for method in ("thread/start", "thread/resume"):
#             self.assertEqual(await self.server.request(method, {"config": self.config}), self.config)
#         self.assertEqual((self.home / "config.toml").read_text(), DRIVER_CONFIG)
#         self.assertEqual((self.owner / ".codex" / "config.toml").read_text(), CONFIG)
#         self.assertFalse(any((self.home / name).exists() for name in ("auth.json", "AGENTS.md", "skills")))
# TEST-TIER-DISABLED-END tests/test_owner_setup.py::OwnerDiagnostics.test_transient_owner_payload_keeps_exact_json_values_and_home_unmodified

# TEST-TIER-DISABLED-BEGIN tests/test_owner_setup.py::OwnerDiagnostics.test_echoed_setup_errors_are_private_and_tool_payloads_are_unchanged
#     async def test_echoed_setup_errors_are_private_and_tool_payloads_are_unchanged(self) -> None:
#         with self.assertRaises(Failure) as caught:
#             await self.server.request("fixture/error", {})
#         error = dumps(caught.exception.result)
#         self.assertNotIn(PRIVATE, error)
#         self.assertNotIn(HEADER, error)
#         self.assertIn("[redacted]", error)
#         await self.server.request("fixture/tool", {})
#         notice = await self.server.next_notification()
#         self.assertEqual(notice.params, {"aggregateOutput": PRIVATE, "input": HEADER})
# TEST-TIER-DISABLED-END tests/test_owner_setup.py::OwnerDiagnostics.test_echoed_setup_errors_are_private_and_tool_payloads_are_unchanged

# TEST-TIER-DISABLED-BEGIN tests/test_owner_setup.py::OwnerDiagnostics.test_split_stderr_values_are_never_retained_or_reported
#     async def test_split_stderr_values_are_never_retained_or_reported(self) -> None:
#         with self.assertRaises(Failure) as caught:
#             await self.server.request("fixture/stderr", {})
#         await asyncio.gather(self.server.tasks[1], return_exceptions=True)
#         self.assertNotIn(PRIVATE, self.server.log_tail)
#         self.assertNotIn(HEADER, self.server.log_tail)
#         self.assertIn("before [redacted] [redacted] after", self.server.log_tail)
#         self.assertNotIn(PRIVATE, dumps(caught.exception.result))
#         self.assertNotIn(HEADER, dumps(caught.exception.result))
# TEST-TIER-DISABLED-END tests/test_owner_setup.py::OwnerDiagnostics.test_split_stderr_values_are_never_retained_or_reported

# Archived complete imports; restore needed names in their original scope, not at this file tail.
# TEST-TIER-IMPORTS-BEGIN tests/test_owner_setup.py:1
# import asyncio
# TEST-TIER-IMPORTS-END tests/test_owner_setup.py:1
# TEST-TIER-IMPORTS-BEGIN tests/test_owner_setup.py:8
# from unittest.mock import patch
# TEST-TIER-IMPORTS-END tests/test_owner_setup.py:8
# TEST-TIER-IMPORTS-BEGIN tests/test_owner_setup.py:10
# from arbol_codex_driver.app_server import DRIVER_CONFIG, AppServer
# TEST-TIER-IMPORTS-END tests/test_owner_setup.py:10
# TEST-TIER-IMPORTS-BEGIN tests/test_owner_setup.py:11
# from arbol_codex_driver.errors import Failure
# TEST-TIER-IMPORTS-END tests/test_owner_setup.py:11
# TEST-TIER-IMPORTS-BEGIN tests/test_owner_setup.py:12
# from arbol_codex_driver.json_types import Object, dumps
# TEST-TIER-IMPORTS-END tests/test_owner_setup.py:12
# TEST-TIER-IMPORTS-BEGIN tests/test_owner_setup.py:13
# from arbol_codex_driver.owner_setup import (
#     DiagnosticScrubber,
#     diagnostic_values,
#     owner_mcp_config,
#     sanitize_diagnostic,
# )
# TEST-TIER-IMPORTS-END tests/test_owner_setup.py:13
