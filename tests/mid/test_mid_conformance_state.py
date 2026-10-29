"""Commented mid-tier selections; see MID_TIER.md before restoring a case."""

# Restore the needed imports and class header only for an explicit testing task.
# import test_conformance_state as _support
# from test_conformance_state import (
#     ConformanceState,
#     LockClock,
#     Path,
#     State,
#     tempfile,
#     unittest,
# )


# class ConformanceState(_support.ConformanceState):
# TEST-TIER-DISABLED-BEGIN tests/test_conformance_state.py::ConformanceState.test_taken_lock_polls_every_50ms_and_fails_after_10s_with_owner
#     async def test_taken_lock_polls_every_50ms_and_fails_after_10s_with_owner(self) -> None:
#         owner = await process_owner(os.getpid())
#         assert owner is not None
#         lock = self.state.subscription("busy") / "lock"
#         write_json(lock, {"owner": owner_json(owner)})
#         original = lock.read_bytes()
#         changed = False
#
#         async def change() -> None:
#             nonlocal changed
#             changed = True
#
#         for scale in (1, 100):
#             with self.subTest(timeScale=scale):
#                 clock = LockClock()
#                 # Replace only this module's clock/sleep surface. The test loop
#                 # still uses its real monotonic clock, and lock files are real.
#                 scheduler = SimpleNamespace(sleep=clock.sleep, to_thread=asyncio.to_thread)
#                 with (
#                     patch.object(state_module, "time", clock),
#                     patch.object(state_module, "asyncio", scheduler),
#                     self.assertRaises(Failure) as caught,
#                 ):
#                     await self.state.with_subscription_lock("busy", change, {"ARBOL_TEST_TIME_SCALE": str(scale)})
#                 self.assertEqual(caught.exception.result["code"], "internal")
#                 message = str(caught.exception.result["message"])
#                 self.assertIn(f"owner PID {owner['pid']}", message)
#                 self.assertIn(owner["startedAt"], message)
#                 self.assertEqual(len(clock.sleeps), 200)
#                 self.assertTrue(all(seconds == 0.05 / scale for seconds in clock.sleeps))
#                 self.assertAlmostEqual(clock.elapsed, 10 / scale)
#                 self.assertFalse(changed)
#                 self.assertEqual(lock.read_bytes(), original)
#                 self.assertEqual(list(lock.parent.glob(".write-*")), [])
# TEST-TIER-DISABLED-END tests/test_conformance_state.py::ConformanceState.test_taken_lock_polls_every_50ms_and_fails_after_10s_with_owner

# TEST-TIER-DISABLED-BEGIN tests/test_conformance_state.py::ConformanceState.test_another_subscription_changes_while_first_lock_is_held
#     async def test_another_subscription_changes_while_first_lock_is_held(self) -> None:
#         held, release = asyncio.Event(), asyncio.Event()
#
#         async def busy_change() -> None:
#             held.set()
#             await release.wait()
#
#         busy = asyncio.create_task(self.state.with_subscription_lock("busy", busy_change))
#         try:
#             await asyncio.wait_for(held.wait(), 1)
#             self.assertTrue((self.state.subscription("busy") / "lock").is_file())
#
#             async def independent_change() -> str:
#                 write_json(self.state.subscription("free") / "record.json", {"label": "Independent"})
#                 return "updated"
#
#             result = await asyncio.wait_for(self.state.with_subscription_lock("free", independent_change), 0.5)
#             self.assertEqual(result, "updated")
#             self.assertFalse(busy.done())
#             self.assertEqual(object_value(read_json(self.state.subscription("free") / "record.json"))["label"],
#                              "Independent")
#             self.assertFalse((self.state.subscription("free") / "lock").exists())
#         finally:
#             release.set()
#             await asyncio.wait_for(busy, 1)
#         self.assertFalse((self.state.subscription("busy") / "lock").exists())
# TEST-TIER-DISABLED-END tests/test_conformance_state.py::ConformanceState.test_another_subscription_changes_while_first_lock_is_held

# TEST-TIER-DISABLED-BEGIN tests/test_conformance_state.py::ConformanceState.test_version_cache_reuses_unchanged_tool_and_invalidates_path_size_and_mtime
#     async def test_version_cache_reuses_unchanged_tool_and_invalidates_path_size_and_mtime(self) -> None:
#         calls = self.folder / "version-calls"
#         tools = self.folder / "tools"
#         tools.mkdir()
#         tool = tools / "codex"
#         tool.write_text(
#             '#!/bin/sh\n[ "$#" -eq 1 ] && [ "$1" = --version ] || exit 64\n'
#             f"printf 'called\\n' >> {shlex.quote(str(calls))}\n"
#             "printf 'codex-cli 0.159.2\\n'\n"
#         )
#         tool.chmod(0o755)
#         env = {"HOME": str(self.folder), "PATH": f"{tools}:/usr/bin:/bin"}
#
#         async def query(path: str | None, expected_calls: int) -> None:
#             info = await inspect_tool(self.state, path, env)
#             self.assertEqual(info["path"], path or str(tool))
#             self.assertEqual((info["version"], info["supported"]), ("0.159.2", True))
#             self.assertEqual(calls.read_text().splitlines(), ["called"] * expected_calls)
#             self.assertEqual(list((self.state.directory / "tmp").iterdir()), [])
#             self.assertEqual((self.state.directory / "tool.json").stat().st_mode & 0o777, 0o600)
#
#         await query(None, 1)  # Resolve from the search path and ask once.
#         first_record = (self.state.directory / "tool.json").read_bytes()
#         await query(None, 1)
#         self.assertEqual((self.state.directory / "tool.json").read_bytes(), first_record)
#
#         before = tool.stat()
#         tool.write_text(tool.read_text() + "# larger executable\n")
#         os.utime(tool, ns=(before.st_atime_ns, before.st_mtime_ns))
#         self.assertNotEqual(tool.stat().st_size, before.st_size)
#         self.assertEqual(tool.stat().st_mtime_ns, before.st_mtime_ns)
#         await query(None, 2)  # Size changed, while the timestamp did not.
#         await query(None, 2)
#
#         before = tool.stat()
#         os.utime(tool, ns=(before.st_atime_ns, before.st_mtime_ns + 5_000_000_000))
#         self.assertEqual(tool.stat().st_size, before.st_size)
#         await query(None, 3)  # Timestamp changed, while the size did not.
#         await query(None, 3)
#
#         alternate = tools / "another-codex"
#         alternate.write_bytes(tool.read_bytes())
#         alternate.chmod(0o755)
#         before = tool.stat()
#         os.utime(alternate, ns=(before.st_atime_ns, before.st_mtime_ns))
#         self.assertEqual((alternate.stat().st_size, alternate.stat().st_mtime_ns),
#                          (tool.stat().st_size, tool.stat().st_mtime_ns))
#         await query(str(alternate), 4)  # A different path with identical metadata.
#         await query(str(alternate), 4)
# TEST-TIER-DISABLED-END tests/test_conformance_state.py::ConformanceState.test_version_cache_reuses_unchanged_tool_and_invalidates_path_size_and_mtime


# Original deferred imports (restore at the required scope, never blindly at the tail).
# TEST-TIER-IMPORTS-BEGIN tests/test_conformance_state.py:5
# import asyncio
# TEST-TIER-IMPORTS-END tests/test_conformance_state.py:5

# TEST-TIER-IMPORTS-BEGIN tests/test_conformance_state.py:6
# import os
# TEST-TIER-IMPORTS-END tests/test_conformance_state.py:6

# TEST-TIER-IMPORTS-BEGIN tests/test_conformance_state.py:7
# import shlex
# TEST-TIER-IMPORTS-END tests/test_conformance_state.py:7

# TEST-TIER-IMPORTS-BEGIN tests/test_conformance_state.py:11
# from types import SimpleNamespace
# TEST-TIER-IMPORTS-END tests/test_conformance_state.py:11

# TEST-TIER-IMPORTS-BEGIN tests/test_conformance_state.py:12
# from unittest.mock import patch
# TEST-TIER-IMPORTS-END tests/test_conformance_state.py:12

# TEST-TIER-IMPORTS-BEGIN tests/test_conformance_state.py:14
# from arbol_codex_driver import state as state_module
# TEST-TIER-IMPORTS-END tests/test_conformance_state.py:14

# TEST-TIER-IMPORTS-BEGIN tests/test_conformance_state.py:15
# from arbol_codex_driver.errors import Failure
# TEST-TIER-IMPORTS-END tests/test_conformance_state.py:15

# TEST-TIER-IMPORTS-BEGIN tests/test_conformance_state.py:16
# from arbol_codex_driver.json_types import object_value
# TEST-TIER-IMPORTS-END tests/test_conformance_state.py:16

# TEST-TIER-IMPORTS-BEGIN tests/test_conformance_state.py:17
# from arbol_codex_driver.state import State, owner_json, process_owner, read_json, write_json
# TEST-TIER-IMPORTS-END tests/test_conformance_state.py:17

# TEST-TIER-IMPORTS-BEGIN tests/test_conformance_state.py:18
# from arbol_codex_driver.tool import inspect_tool
# TEST-TIER-IMPORTS-END tests/test_conformance_state.py:18

raise RuntimeError("Mid-tier tests require an explicitly requested testing task; see MID_TIER.md.")
