"""Mid-tier selections. Write or run only in an explicitly requested testing task."""
from __future__ import annotations

import test_process_groups as _support
from test_process_groups import (
    AsyncMock,
    ForcedProcessGroupTests,
    Owner,
    ProcessGroupTests,
    ProcessSnapshot,
    descendant_process_groups,
    end_process_groups,
    force_process_groups,
    iso,
    owner,
    patch,
    row,
    same_owner,
    signal,
    surviving_process_groups,
    time,
    unittest,
)


class ProcessGroupTests(_support.ProcessGroupTests):
# TEST-TIER-BEGIN tests/test_process_groups.py::ProcessGroupTests.test_same_owner_requires_pid_and_start_time_with_two_second_tolerance
    def test_same_owner_requires_pid_and_start_time_with_two_second_tolerance(self) -> None:
        self.assertTrue(same_owner(owner(10, 1002), owner(10)))
        self.assertFalse(same_owner(owner(11), owner(10)))
        self.assertFalse(same_owner(owner(10, 1002.001), owner(10)))
# TEST-TIER-END tests/test_process_groups.py::ProcessGroupTests.test_same_owner_requires_pid_and_start_time_with_two_second_tolerance

# TEST-TIER-BEGIN tests/test_process_groups.py::ProcessGroupTests.test_reused_group_leader_is_never_selected
    def test_reused_group_leader_is_never_selected(self) -> None:
        table = [row(10, 10, started=1005), row(11, 10, parent=10)]
        self.assertEqual(surviving_process_groups([owner(10)], table), [])
        self.assertEqual(descendant_process_groups(owner(10), table), [])
# TEST-TIER-END tests/test_process_groups.py::ProcessGroupTests.test_reused_group_leader_is_never_selected

# TEST-TIER-BEGIN tests/test_process_groups.py::ProcessGroupTests.test_live_leader_in_another_group_is_never_selected
    def test_live_leader_in_another_group_is_never_selected(self) -> None:
        table = [row(10, 20), row(11, 10, parent=10)]
        self.assertEqual(surviving_process_groups([owner(10)], table), [])
        self.assertEqual(descendant_process_groups(owner(10), table), [])
# TEST-TIER-END tests/test_process_groups.py::ProcessGroupTests.test_live_leader_in_another_group_is_never_selected

# TEST-TIER-BEGIN tests/test_process_groups.py::ProcessGroupTests.test_departed_leader_keeps_its_surviving_members_owned
    def test_departed_leader_keeps_its_surviving_members_owned(self) -> None:
        table = [row(11, 10)]
        self.assertEqual(surviving_process_groups([owner(10)], table), [owner(10)])
        self.assertEqual(descendant_process_groups(owner(10), table), [owner(10)])
# TEST-TIER-END tests/test_process_groups.py::ProcessGroupTests.test_departed_leader_keeps_its_surviving_members_owned

# TEST-TIER-BEGIN tests/test_process_groups.py::ProcessGroupTests.test_departed_leader_without_members_is_finished
    def test_departed_leader_without_members_is_finished(self) -> None:
        table = [row(20, 20)]
        self.assertEqual(surviving_process_groups([owner(10)], table), [])
        self.assertEqual(descendant_process_groups(owner(10), table), [])
# TEST-TIER-END tests/test_process_groups.py::ProcessGroupTests.test_departed_leader_without_members_is_finished

# TEST-TIER-BEGIN tests/test_process_groups.py::ProcessGroupTests.test_zombie_only_group_is_finished
    def test_zombie_only_group_is_finished(self) -> None:
        table = [row(10, 10, zombie=True), row(11, 10, parent=10, zombie=True)]
        self.assertEqual(surviving_process_groups([owner(10)], table), [])
        self.assertEqual(descendant_process_groups(owner(10), table), [])
# TEST-TIER-END tests/test_process_groups.py::ProcessGroupTests.test_zombie_only_group_is_finished

# TEST-TIER-BEGIN tests/test_process_groups.py::ProcessGroupTests.test_verified_group_collects_nested_descendants_and_separate_groups
    def test_verified_group_collects_nested_descendants_and_separate_groups(self) -> None:
        table = [
            row(10, 10),
            row(11, 10, parent=10),
            row(20, 20, parent=11),
            row(21, 20, parent=20),
            row(30, 30, parent=21),
            row(99, 99),
        ]
        self.assertEqual(descendant_process_groups(owner(10), table), [owner(10), owner(20), owner(30)])
        self.assertEqual(
            surviving_process_groups([owner(10), owner(20), owner(30)], table), [owner(10), owner(20), owner(30)]
        )
# TEST-TIER-END tests/test_process_groups.py::ProcessGroupTests.test_verified_group_collects_nested_descendants_and_separate_groups

# TEST-TIER-BEGIN tests/test_process_groups.py::ProcessGroupTests.test_duplicate_owners_are_signalled_only_once
    def test_duplicate_owners_are_signalled_only_once(self) -> None:
        table = [row(10, 10)]
        self.assertEqual(surviving_process_groups([owner(10), owner(10)], table), [owner(10)])
# TEST-TIER-END tests/test_process_groups.py::ProcessGroupTests.test_duplicate_owners_are_signalled_only_once



class ForcedProcessGroupTests(_support.ForcedProcessGroupTests):
# TEST-TIER-BEGIN tests/test_process_groups.py::ForcedProcessGroupTests.test_immediate_kill_requires_fresh_snapshot_and_surviving_member
    async def test_immediate_kill_requires_fresh_snapshot_and_surviving_member(self) -> None:
        for table in ([row(10, 10)], [row(11, 10)]):
            with (
                self.subTest(table=table),
                patch("arbol_codex_driver.process_groups.process_snapshot", AsyncMock(return_value=table)) as snapshot,
                patch("arbol_codex_driver.process_groups.os.killpg") as kill,
            ):
                await force_process_groups([owner(10)], time.monotonic() + 1)
                snapshot.assert_awaited_once()
                kill.assert_called_once_with(10, signal.SIGKILL)
# TEST-TIER-END tests/test_process_groups.py::ForcedProcessGroupTests.test_immediate_kill_requires_fresh_snapshot_and_surviving_member

# TEST-TIER-BEGIN tests/test_process_groups.py::ForcedProcessGroupTests.test_a_group_that_is_ending_may_answer_eperm
    async def test_a_group_that_is_ending_may_answer_eperm(self) -> None:
        # macOS answers EPERM for a group whose processes have exited but are not yet reaped.
        with (
            patch("arbol_codex_driver.process_groups.process_snapshot", AsyncMock(return_value=[row(10, 10)])),
            patch("arbol_codex_driver.process_groups.os.killpg", side_effect=PermissionError) as kill,
        ):
            await force_process_groups([owner(10)], time.monotonic() + 1)
            kill.assert_called_once_with(10, signal.SIGKILL)
        tables = AsyncMock(side_effect=[[row(10, 10)], []])
        with (
            patch("arbol_codex_driver.process_groups.process_snapshot", tables),
            patch("arbol_codex_driver.process_groups.os.killpg", side_effect=PermissionError) as kill,
        ):
            self.assertEqual(await end_process_groups([owner(10)], time.monotonic() + 1), [])
            kill.assert_called_once_with(10, signal.SIGTERM)
# TEST-TIER-END tests/test_process_groups.py::ForcedProcessGroupTests.test_a_group_that_is_ending_may_answer_eperm
