# Shared fixtures; case bodies live in top/ and mid/. See TESTS.md.
"""Delivery boundaries: pinned archives, numbered records and nonempty checks."""

from __future__ import annotations
import hashlib
import json
import os
import tempfile
from unittest.mock import patch


import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_support  # noqa: E402
import check_build  # noqa: E402
import package_build  # noqa: E402


class PackagingTests(unittest.TestCase):
    pass  # TEST-TIER-EMPTY-SUITE; helpers remain importable.


# Archived complete imports; restore needed names in their original scope, not at this file tail.

# LOW TIER — DO NOT ENABLE OR RECREATE
# Historical examples only. Read before adding related tests; never execute.
# LOW-TIER-BEGIN: tests/test_packaging.py::PackagingTests.test_package_metadata_must_agree
# Reason: Sets two version strings to unequal values and asserts the explicit equality guard; no package installation or compatibility boundary is exercised.
# Source: arbol-codex-driver@970250923b38583493ecf02c04c66370ecbafd47:tests/test_packaging.py
# Retained evidence at review: Archive-integrity and numbered-build identity/entry refusal tests remain.
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     def test_package_metadata_must_agree(self) -> None:
#         with tempfile.TemporaryDirectory() as name:
#             root = Path(name)
#             (root / "pyproject.toml").write_text(
#                 f'[project]\nname = "{build_support.COMPONENT}"\nversion = "1.0.0"\ndependencies = []\n'
#             )
#             (root / "package.json").write_text('{"version":"9.0.0"}\n')
#             with self.assertRaisesRegex(ValueError, "agree on the package version"):
#                 build_support.metadata(root)
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/test_packaging.py::PackagingTests.test_contract_gate_takes_the_suite_from_readonly
# Reason: Mocks the runner and checks only the default/overridden path concatenated into its argv; it does not establish conformance.
# Source: arbol-codex-driver@970250923b38583493ecf02c04c66370ecbafd47:tests/test_packaging.py
# Retained evidence at review: Actual conformance runner/scenario tests and gate failure/empty-suite protection remain.
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     def test_contract_gate_takes_the_suite_from_readonly(self) -> None:
#         with tempfile.TemporaryDirectory() as name:
#             home, other = Path(name).resolve() / "home", Path(name).resolve() / "other checkout"
#             for repo in (home / "repos/sylvan-stack/readonly/arbol", other):
#                 repo.mkdir(parents=True)
#                 (repo / "package.json").write_text(json.dumps({"name": "@sylvan-stack/arbol"}))
#             environment = {key: value for key, value in os.environ.items() if key != "ARBOL_CONFORMANCE_REPO"}
#             with (
#                 patch.dict(os.environ, {**environment, "HOME": str(home)}, clear=True),
#                 patch.object(check_build, "run", return_value=0) as execute,
#             ):
#                 self.assertEqual(check_build.contract(Path("/tmp/candidate")), 0)
#             self.assertEqual(execute.call_args.args[0][3],
#                              str(home / "repos/sylvan-stack/readonly/arbol/conformance/bin/arbol-conformance.py"))
#             with (
#                 patch.dict(os.environ, {"HOME": str(home), "ARBOL_CONFORMANCE_REPO": str(other)}),
#                 patch.object(check_build, "run", return_value=0) as execute,
#             ):
#                 check_build.contract(Path("/tmp/candidate"))
#             self.assertEqual(execute.call_args.args[0][3], str(other / "conformance/bin/arbol-conformance.py"))
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/test_packaging.py::PackagingTests.test_live_gate_defaults_to_the_test_state_directory
# Reason: Mocks execution and compares a literal default directory appended to the current home.
# Source: arbol-codex-driver@970250923b38583493ecf02c04c66370ecbafd47:tests/test_packaging.py
# Retained evidence at review: Explicit private environment/packaged entry and invalid-state-directory guard cases remain.
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     def test_live_gate_defaults_to_the_test_state_directory(self) -> None:
#         environment = {key: value for key, value in os.environ.items() if key != "ARBOL_BUILD_TEST_STATE_DIR"}
#         with patch.dict(os.environ, environment, clear=True), patch.object(check_build, "run", return_value=0) as execute:
#             self.assertEqual(check_build.live(Path("/tmp/candidate")), 0)
#         home = Path(pwd.getpwuid(os.getuid()).pw_dir)
#         self.assertEqual(execute.call_args.args[0][-2:],
#                          ["--state-dir", str(home / "Library/Application Support/Arbol/drivers/arbol-codex-driver")])
# LOW-TIER-SOURCE-END
# LOW-TIER-END
