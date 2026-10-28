"""Process-table identity checks protect unrelated processes during cleanup."""

from __future__ import annotations

import time
import unittest
from unittest.mock import AsyncMock, patch

from arbol_codex_driver.json_types import iso
from arbol_codex_driver.process_groups import (
    ProcessSnapshot,
    force_process_groups,
)
from arbol_codex_driver.state import Owner


def owner(pid: int, started: float = 1000) -> Owner:
    return {"pid": pid, "startedAt": iso(started)}


def row(pid: int, group: int, parent: int = 1, started: float = 1000, zombie: bool = False) -> ProcessSnapshot:
    return {"pid": pid, "startedAt": iso(started), "parentId": parent, "groupId": group, "zombie": zombie}


class ProcessGroupTests(unittest.TestCase):
    pass  # TEST-TIER-EMPTY-SUITE; helpers remain importable.
# TEST-TIER-DISABLED-BEGIN tests/test_process_groups.py::ProcessGroupTests.test_same_owner_requires_pid_and_start_time_with_two_second_tolerance
#     def test_same_owner_requires_pid_and_start_time_with_two_second_tolerance(self) -> None:
#         self.assertTrue(same_owner(owner(10, 1002), owner(10)))
#         self.assertFalse(same_owner(owner(11), owner(10)))
#         self.assertFalse(same_owner(owner(10, 1002.001), owner(10)))
# TEST-TIER-DISABLED-END tests/test_process_groups.py::ProcessGroupTests.test_same_owner_requires_pid_and_start_time_with_two_second_tolerance

# TEST-TIER-DISABLED-BEGIN tests/test_process_groups.py::ProcessGroupTests.test_reused_group_leader_is_never_selected
#     def test_reused_group_leader_is_never_selected(self) -> None:
#         table = [row(10, 10, started=1005), row(11, 10, parent=10)]
#         self.assertEqual(surviving_process_groups([owner(10)], table), [])
#         self.assertEqual(descendant_process_groups(owner(10), table), [])
# TEST-TIER-DISABLED-END tests/test_process_groups.py::ProcessGroupTests.test_reused_group_leader_is_never_selected

# TEST-TIER-DISABLED-BEGIN tests/test_process_groups.py::ProcessGroupTests.test_live_leader_in_another_group_is_never_selected
#     def test_live_leader_in_another_group_is_never_selected(self) -> None:
#         table = [row(10, 20), row(11, 10, parent=10)]
#         self.assertEqual(surviving_process_groups([owner(10)], table), [])
#         self.assertEqual(descendant_process_groups(owner(10), table), [])
# TEST-TIER-DISABLED-END tests/test_process_groups.py::ProcessGroupTests.test_live_leader_in_another_group_is_never_selected

# TEST-TIER-DISABLED-BEGIN tests/test_process_groups.py::ProcessGroupTests.test_departed_leader_keeps_its_surviving_members_owned
#     def test_departed_leader_keeps_its_surviving_members_owned(self) -> None:
#         table = [row(11, 10)]
#         self.assertEqual(surviving_process_groups([owner(10)], table), [owner(10)])
#         self.assertEqual(descendant_process_groups(owner(10), table), [owner(10)])
# TEST-TIER-DISABLED-END tests/test_process_groups.py::ProcessGroupTests.test_departed_leader_keeps_its_surviving_members_owned

# TEST-TIER-DISABLED-BEGIN tests/test_process_groups.py::ProcessGroupTests.test_departed_leader_without_members_is_finished
#     def test_departed_leader_without_members_is_finished(self) -> None:
#         table = [row(20, 20)]
#         self.assertEqual(surviving_process_groups([owner(10)], table), [])
#         self.assertEqual(descendant_process_groups(owner(10), table), [])
# TEST-TIER-DISABLED-END tests/test_process_groups.py::ProcessGroupTests.test_departed_leader_without_members_is_finished

# TEST-TIER-DISABLED-BEGIN tests/test_process_groups.py::ProcessGroupTests.test_zombie_only_group_is_finished
#     def test_zombie_only_group_is_finished(self) -> None:
#         table = [row(10, 10, zombie=True), row(11, 10, parent=10, zombie=True)]
#         self.assertEqual(surviving_process_groups([owner(10)], table), [])
#         self.assertEqual(descendant_process_groups(owner(10), table), [])
# TEST-TIER-DISABLED-END tests/test_process_groups.py::ProcessGroupTests.test_zombie_only_group_is_finished

# TEST-TIER-DISABLED-BEGIN tests/test_process_groups.py::ProcessGroupTests.test_verified_group_collects_nested_descendants_and_separate_groups
#     def test_verified_group_collects_nested_descendants_and_separate_groups(self) -> None:
#         table = [
#             row(10, 10),
#             row(11, 10, parent=10),
#             row(20, 20, parent=11),
#             row(21, 20, parent=20),
#             row(30, 30, parent=21),
#             row(99, 99),
#         ]
#         self.assertEqual(descendant_process_groups(owner(10), table), [owner(10), owner(20), owner(30)])
#         self.assertEqual(
#             surviving_process_groups([owner(10), owner(20), owner(30)], table), [owner(10), owner(20), owner(30)]
#         )
# TEST-TIER-DISABLED-END tests/test_process_groups.py::ProcessGroupTests.test_verified_group_collects_nested_descendants_and_separate_groups

# TEST-TIER-DISABLED-BEGIN tests/test_process_groups.py::ProcessGroupTests.test_duplicate_owners_are_signalled_only_once
#     def test_duplicate_owners_are_signalled_only_once(self) -> None:
#         table = [row(10, 10)]
#         self.assertEqual(surviving_process_groups([owner(10), owner(10)], table), [owner(10)])
# TEST-TIER-DISABLED-END tests/test_process_groups.py::ProcessGroupTests.test_duplicate_owners_are_signalled_only_once


class ForcedProcessGroupTests(unittest.IsolatedAsyncioTestCase):
    async def test_immediate_kill_refuses_reused_or_wrong_group_leaders(self) -> None:
        for table in ([row(10, 10, started=1005)], [row(10, 20)]):
            with (
                self.subTest(table=table),
                patch("arbol_codex_driver.process_groups.process_snapshot", AsyncMock(return_value=table)),
                patch("arbol_codex_driver.process_groups.os.killpg") as kill,
            ):
                await force_process_groups([owner(10)], time.monotonic() + 1)
                kill.assert_not_called()

# TEST-TIER-DISABLED-BEGIN tests/test_process_groups.py::ForcedProcessGroupTests.test_immediate_kill_requires_fresh_snapshot_and_surviving_member
#     async def test_immediate_kill_requires_fresh_snapshot_and_surviving_member(self) -> None:
#         for table in ([row(10, 10)], [row(11, 10)]):
#             with (
#                 self.subTest(table=table),
#                 patch("arbol_codex_driver.process_groups.process_snapshot", AsyncMock(return_value=table)) as snapshot,
#                 patch("arbol_codex_driver.process_groups.os.killpg") as kill,
#             ):
#                 await force_process_groups([owner(10)], time.monotonic() + 1)
#                 snapshot.assert_awaited_once()
#                 kill.assert_called_once_with(10, signal.SIGKILL)
# TEST-TIER-DISABLED-END tests/test_process_groups.py::ForcedProcessGroupTests.test_immediate_kill_requires_fresh_snapshot_and_surviving_member

# TEST-TIER-DISABLED-BEGIN tests/test_process_groups.py::ForcedProcessGroupTests.test_a_group_that_is_ending_may_answer_eperm
#     async def test_a_group_that_is_ending_may_answer_eperm(self) -> None:
#         # macOS answers EPERM for a group whose processes have exited but are not yet reaped.
#         with (
#             patch("arbol_codex_driver.process_groups.process_snapshot", AsyncMock(return_value=[row(10, 10)])),
#             patch("arbol_codex_driver.process_groups.os.killpg", side_effect=PermissionError) as kill,
#         ):
#             await force_process_groups([owner(10)], time.monotonic() + 1)
#             kill.assert_called_once_with(10, signal.SIGKILL)
#         tables = AsyncMock(side_effect=[[row(10, 10)], []])
#         with (
#             patch("arbol_codex_driver.process_groups.process_snapshot", tables),
#             patch("arbol_codex_driver.process_groups.os.killpg", side_effect=PermissionError) as kill,
#         ):
#             self.assertEqual(await end_process_groups([owner(10)], time.monotonic() + 1), [])
#             kill.assert_called_once_with(10, signal.SIGTERM)
# TEST-TIER-DISABLED-END tests/test_process_groups.py::ForcedProcessGroupTests.test_a_group_that_is_ending_may_answer_eperm


if __name__ == "__main__":
    unittest.main()

# Archived complete imports; restore needed names in their original scope, not at this file tail.
# TEST-TIER-IMPORTS-BEGIN tests/test_process_groups.py:5
# import signal
# TEST-TIER-IMPORTS-END tests/test_process_groups.py:5
# TEST-TIER-IMPORTS-BEGIN tests/test_process_groups.py:11
# from arbol_codex_driver.process_groups import (
#     ProcessSnapshot,
#     descendant_process_groups,
#     end_process_groups,
#     force_process_groups,
#     same_owner,
#     surviving_process_groups,
# )
# TEST-TIER-IMPORTS-END tests/test_process_groups.py:11
