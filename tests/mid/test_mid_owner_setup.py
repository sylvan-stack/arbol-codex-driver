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

# LOW TIER — DO NOT ENABLE OR RECREATE
# Historical examples only. Read before adding related tests; never execute.
# LOW-TIER-BEGIN: tests/mid/test_mid_owner_setup.py::OwnerSetup.test_preserves_mcp_tables_and_reads_no_other_owner_file
# Reason: Rechecks local MCP-table defaults/validation or manually configured transport echo values. Retained real resumed-owner workflow and diagnostic redaction cases establish the consequential configuration and privacy boundaries. Case reviewed: Preserves mcp tables and reads no other owner file.
# Source: arbol-codex-driver@0c596c5960c34039bd48d05df9b66b4ea9f31680:tests/mid/test_mid_owner_setup.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
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
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_owner_setup.py::OwnerSetup.test_missing_tables_empty_table_and_each_run_reads_current_owner_home
# Reason: Rechecks local MCP-table defaults/validation or manually configured transport echo values. Retained real resumed-owner workflow and diagnostic redaction cases establish the consequential configuration and privacy boundaries. Case reviewed: Missing tables empty table and each run reads current owner home.
# Source: arbol-codex-driver@0c596c5960c34039bd48d05df9b66b4ea9f31680:tests/mid/test_mid_owner_setup.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
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
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_owner_setup.py::OwnerSetup.test_malformed_unreadable_and_non_json_tables_have_nonsecret_errors
# Reason: Rechecks local MCP-table defaults/validation or manually configured transport echo values. Retained real resumed-owner workflow and diagnostic redaction cases establish the consequential configuration and privacy boundaries. Case reviewed: Malformed unreadable and non json tables have nonsecret errors.
# Source: arbol-codex-driver@0c596c5960c34039bd48d05df9b66b4ea9f31680:tests/mid/test_mid_owner_setup.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
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
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_owner_setup.py::OwnerSetup.test_diagnostics_scrub_longest_literals_and_preserve_structured_fields
# Reason: Rechecks local MCP-table defaults/validation or manually configured transport echo values. Retained real resumed-owner workflow and diagnostic redaction cases establish the consequential configuration and privacy boundaries. Case reviewed: Diagnostics scrub longest literals and preserve structured fields.
# Source: arbol-codex-driver@0c596c5960c34039bd48d05df9b66b4ea9f31680:tests/mid/test_mid_owner_setup.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
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
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_owner_setup.py::OwnerDiagnostics.test_transient_owner_payload_keeps_exact_json_values_and_home_unmodified
# Reason: Rechecks local MCP-table defaults/validation or manually configured transport echo values. Retained real resumed-owner workflow and diagnostic redaction cases establish the consequential configuration and privacy boundaries. Case reviewed: Transient owner payload keeps exact json values and home unmodified.
# Source: arbol-codex-driver@0c596c5960c34039bd48d05df9b66b4ea9f31680:tests/mid/test_mid_owner_setup.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_transient_owner_payload_keeps_exact_json_values_and_home_unmodified(self) -> None:
#         for method in ("thread/start", "thread/resume"):
#             self.assertEqual(await self.server.request(method, {"config": self.config}), self.config)
#         self.assertEqual((self.home / "config.toml").read_text(), DRIVER_CONFIG)
#         self.assertEqual((self.owner / ".codex" / "config.toml").read_text(), CONFIG)
#         self.assertFalse(any((self.home / name).exists() for name in ("auth.json", "AGENTS.md", "skills")))
# LOW-TIER-SOURCE-END
# LOW-TIER-END
