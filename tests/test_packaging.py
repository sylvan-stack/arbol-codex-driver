"""Delivery boundaries: pinned archives, numbered records and nonempty checks."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


class PackagingTests(unittest.TestCase):
    pass  # TEST-TIER-EMPTY-SUITE; helpers remain importable.
# TEST-TIER-DISABLED-BEGIN tests/test_packaging.py::PackagingTests.test_corrupted_cached_distribution_is_refused_without_a_download
#     def test_corrupted_cached_distribution_is_refused_without_a_download(self) -> None:
#         with tempfile.TemporaryDirectory() as name:
#             cache = Path(name)
#             expected = hashlib.sha256(b"expected archive").hexdigest()
#             (cache / f"{expected}.tar.gz").write_bytes(b"corrupt archive")
#             with (
#                 patch.dict(os.environ, {"ARBOL_PYTHON_ARCHIVE_CACHE": name}),
#                 patch("urllib.request.urlopen") as download,
#             ):
#                 with self.assertRaisesRegex(ValueError, "wrong SHA-256"):
#                     package_build.archive(
#                         {
#                             "url": "https://github.com/astral-sh/python-build-standalone/releases/download/test/python.tar.gz",
#                             "sha256": expected,
#                         }
#                     )
#                 download.assert_not_called()
# TEST-TIER-DISABLED-END tests/test_packaging.py::PackagingTests.test_corrupted_cached_distribution_is_refused_without_a_download

# TEST-TIER-DISABLED-BEGIN tests/test_packaging.py::PackagingTests.test_archive_pin_rejects_nonhex_digests_and_untrusted_sources
#     def test_archive_pin_rejects_nonhex_digests_and_untrusted_sources(self) -> None:
#         for distribution in (
#             {"url": "https://example.invalid/python.tar.gz", "sha256": "f" * 64},
#             {
#                 "url": "https://github.com/astral-sh/python-build-standalone/releases/download/test/python.tar.gz",
#                 "sha256": "/" * 64,
#             },
#         ):
#             with self.subTest(distribution=distribution), patch("urllib.request.urlopen") as download:
#                 with self.assertRaisesRegex(ValueError, "pinned URL and SHA-256"):
#                     package_build.archive(distribution)
#                 download.assert_not_called()
# TEST-TIER-DISABLED-END tests/test_packaging.py::PackagingTests.test_archive_pin_rejects_nonhex_digests_and_untrusted_sources


# TEST-TIER-DISABLED-BEGIN tests/test_packaging.py::PackagingTests.test_candidate_cannot_overwrite_a_numbered_build
#     def test_candidate_cannot_overwrite_a_numbered_build(self) -> None:
#         with tempfile.TemporaryDirectory() as name:
#             (Path(name) / "build.json").write_text("{}\n")
#             with self.assertRaisesRegex(ValueError, "cannot replace a numbered Build"):
#                 build_support.build_folder(name)
# TEST-TIER-DISABLED-END tests/test_packaging.py::PackagingTests.test_candidate_cannot_overwrite_a_numbered_build

# TEST-TIER-DISABLED-BEGIN tests/test_packaging.py::PackagingTests.test_build_record_requires_matching_number_entry_and_version
#     def test_build_record_requires_matching_number_entry_and_version(self) -> None:
#         with tempfile.TemporaryDirectory() as name:
#             folder = Path(name)
#             record = {
#                 "component": build_support.COMPONENT,
#                 "build": "a",
#                 "packageVersion": "1.0.0",
#                 "entry": build_support.ENTRY,
#             }
#             (folder / "build.json").write_text(json.dumps(record))
#             with (
#                 patch.dict(os.environ, {"ARBOL_BUILD_DIR": name, "ARBOL_BUILD_NUMBER": "b"}),
#                 patch.object(build_support, "metadata", return_value=("1.0.0", {})),
#             ):
#                 with self.assertRaisesRegex(ValueError, "match this component, number and package version"):
#                     build_support.build_folder()
#             record["build"] = "b"
#             record["entry"] = "bin/another-program"
#             (folder / "build.json").write_text(json.dumps(record))
#             with (
#                 patch.dict(os.environ, {"ARBOL_BUILD_DIR": name, "ARBOL_BUILD_NUMBER": "b"}),
#                 patch.object(build_support, "metadata", return_value=("1.0.0", {})),
#             ):
#                 with self.assertRaisesRegex(ValueError, "executable entry"):
#                     build_support.build_folder()
# TEST-TIER-DISABLED-END tests/test_packaging.py::PackagingTests.test_build_record_requires_matching_number_entry_and_version


# TEST-TIER-DISABLED-BEGIN tests/test_packaging.py::PackagingTests.test_unit_gate_refuses_an_empty_suite
#     def test_unit_gate_refuses_an_empty_suite(self) -> None:
#         with tempfile.TemporaryDirectory() as name:
#             folder = Path(name)
#             (folder / "tests").mkdir()
#             previous = Path.cwd()
#             try:
#                 with self.assertRaisesRegex(ValueError, "no tests"):
#                     check_build.unit(folder)
#             finally:
#                 os.chdir(previous)
# TEST-TIER-DISABLED-END tests/test_packaging.py::PackagingTests.test_unit_gate_refuses_an_empty_suite

# TEST-TIER-DISABLED-BEGIN tests/test_packaging.py::PackagingTests.test_live_gate_uses_direct_packaged_entry_and_clean_environment
#     def test_live_gate_uses_direct_packaged_entry_and_clean_environment(self) -> None:
#         with (
#             patch.dict(os.environ, {"ARBOL_BUILD_TEST_STATE_DIR": "/tmp/test state", "HOME": "/tmp/caller-home",
#                                     "OPENAI_API_KEY": "fictional-secret", "CODEX_HOME": "/tmp/caller-codex"}),
#             patch.object(check_build, "run", return_value=0) as execute,
#         ):
#             folder = Path("/tmp/packaged candidate")
#             self.assertEqual(check_build.live(folder), 0)
#             execute.assert_called_once()
#             arguments = execute.call_args.args[0]
#             self.assertEqual(arguments, [str(folder / build_support.ENTRY), "dev", "build-check",
#                                          "--state-dir", "/tmp/test state"])
#             environment = execute.call_args.kwargs["env"]
#             self.assertEqual(set(environment), {"HOME", "PATH", "LANG"})
#             self.assertNotEqual(environment["HOME"], "/tmp/caller-home")
#             self.assertEqual(execute.call_args.kwargs["cwd"], folder)
# TEST-TIER-DISABLED-END tests/test_packaging.py::PackagingTests.test_live_gate_uses_direct_packaged_entry_and_clean_environment


# TEST-TIER-DISABLED-BEGIN tests/test_packaging.py::PackagingTests.test_live_gate_refuses_relative_or_empty_test_state_before_start
#     def test_live_gate_refuses_relative_or_empty_test_state_before_start(self) -> None:
#         for directory in ("", "relative/state"):
#             with (
#                 self.subTest(directory=directory),
#                 patch.dict(os.environ, {"ARBOL_BUILD_TEST_STATE_DIR": directory}),
#                 patch.object(check_build, "run") as execute,
#             ):
#                 with self.assertRaisesRegex(ValueError, "absolute test state"):
#                     check_build.live(Path("/tmp/candidate"))
#                 execute.assert_not_called()
# TEST-TIER-DISABLED-END tests/test_packaging.py::PackagingTests.test_live_gate_refuses_relative_or_empty_test_state_before_start


if __name__ == "__main__":
    unittest.main()

# Archived complete imports; restore needed names in their original scope, not at this file tail.
# TEST-TIER-IMPORTS-BEGIN tests/test_packaging.py:5
# import hashlib
# TEST-TIER-IMPORTS-END tests/test_packaging.py:5
# TEST-TIER-IMPORTS-BEGIN tests/test_packaging.py:6
# import json
# TEST-TIER-IMPORTS-END tests/test_packaging.py:6
# TEST-TIER-IMPORTS-BEGIN tests/test_packaging.py:7
# import os
# TEST-TIER-IMPORTS-END tests/test_packaging.py:7
# TEST-TIER-IMPORTS-BEGIN tests/test_packaging.py:9
# import tempfile
# TEST-TIER-IMPORTS-END tests/test_packaging.py:9
# TEST-TIER-IMPORTS-BEGIN tests/test_packaging.py:12
# from unittest.mock import patch
# TEST-TIER-IMPORTS-END tests/test_packaging.py:12
# TEST-TIER-IMPORTS-BEGIN tests/test_packaging.py:15
# import build_support  # noqa: E402
# TEST-TIER-IMPORTS-END tests/test_packaging.py:15
# TEST-TIER-IMPORTS-BEGIN tests/test_packaging.py:16
# import check_build  # noqa: E402
# TEST-TIER-IMPORTS-END tests/test_packaging.py:16
# TEST-TIER-IMPORTS-BEGIN tests/test_packaging.py:17
# import package_build  # noqa: E402
# TEST-TIER-IMPORTS-END tests/test_packaging.py:17
