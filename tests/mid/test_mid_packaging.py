
# LOW TIER — DO NOT ENABLE OR RECREATE
# Historical examples only. Read before adding related tests; never execute.
# LOW-TIER-BEGIN: tests/mid/test_mid_packaging.py::PackagingTests.test_corrupted_cached_distribution_is_refused_without_a_download
# Reason: Repeats straightforward packaging metadata/gate predicates or the copied archive-cache mechanism. Actual candidate relocation/registry verification is retained, and the classifier retains the representative corrupt-cache check; production release gates remain unchanged. Case reviewed: Corrupted cached distribution is refused without a download.
# Source: arbol-codex-driver@0c596c5960c34039bd48d05df9b66b4ea9f31680:tests/mid/test_mid_packaging.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
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
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_packaging.py::PackagingTests.test_archive_pin_rejects_nonhex_digests_and_untrusted_sources
# Reason: Repeats straightforward packaging metadata/gate predicates or the copied archive-cache mechanism. Actual candidate relocation/registry verification is retained, and the classifier retains the representative corrupt-cache check; production release gates remain unchanged. Case reviewed: Archive pin rejects nonhex digests and untrusted sources.
# Source: arbol-codex-driver@0c596c5960c34039bd48d05df9b66b4ea9f31680:tests/mid/test_mid_packaging.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
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
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_packaging.py::PackagingTests.test_candidate_cannot_overwrite_a_numbered_build
# Reason: Repeats straightforward packaging metadata/gate predicates or the copied archive-cache mechanism. Actual candidate relocation/registry verification is retained, and the classifier retains the representative corrupt-cache check; production release gates remain unchanged. Case reviewed: Candidate cannot overwrite a numbered build.
# Source: arbol-codex-driver@0c596c5960c34039bd48d05df9b66b4ea9f31680:tests/mid/test_mid_packaging.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     def test_candidate_cannot_overwrite_a_numbered_build(self) -> None:
#         with tempfile.TemporaryDirectory() as name:
#             (Path(name) / "build.json").write_text("{}\n")
#             with self.assertRaisesRegex(ValueError, "cannot replace a numbered Build"):
#                 build_support.build_folder(name)
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_packaging.py::PackagingTests.test_build_record_requires_matching_number_entry_and_version
# Reason: Repeats straightforward packaging metadata/gate predicates or the copied archive-cache mechanism. Actual candidate relocation/registry verification is retained, and the classifier retains the representative corrupt-cache check; production release gates remain unchanged. Case reviewed: Build record requires matching number entry and version.
# Source: arbol-codex-driver@0c596c5960c34039bd48d05df9b66b4ea9f31680:tests/mid/test_mid_packaging.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
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
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_packaging.py::PackagingTests.test_unit_gate_refuses_an_empty_suite
# Reason: Repeats straightforward packaging metadata/gate predicates or the copied archive-cache mechanism. Actual candidate relocation/registry verification is retained, and the classifier retains the representative corrupt-cache check; production release gates remain unchanged. Case reviewed: Unit gate refuses an empty suite.
# Source: arbol-codex-driver@0c596c5960c34039bd48d05df9b66b4ea9f31680:tests/mid/test_mid_packaging.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
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
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_packaging.py::PackagingTests.test_live_gate_uses_direct_packaged_entry_and_clean_environment
# Reason: Repeats straightforward packaging metadata/gate predicates or the copied archive-cache mechanism. Actual candidate relocation/registry verification is retained, and the classifier retains the representative corrupt-cache check; production release gates remain unchanged. Case reviewed: Live gate uses direct packaged entry and clean environment.
# Source: arbol-codex-driver@0c596c5960c34039bd48d05df9b66b4ea9f31680:tests/mid/test_mid_packaging.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
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
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_packaging.py::PackagingTests.test_live_gate_refuses_relative_or_empty_test_state_before_start
# Reason: Repeats straightforward packaging metadata/gate predicates or the copied archive-cache mechanism. Actual candidate relocation/registry verification is retained, and the classifier retains the representative corrupt-cache check; production release gates remain unchanged. Case reviewed: Live gate refuses relative or empty test state before start.
# Source: arbol-codex-driver@0c596c5960c34039bd48d05df9b66b4ea9f31680:tests/mid/test_mid_packaging.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
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
# LOW-TIER-SOURCE-END
# LOW-TIER-END
