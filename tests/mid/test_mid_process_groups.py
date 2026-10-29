
# LOW TIER — DO NOT ENABLE OR RECREATE
# Historical examples only. Read before adding related tests; never execute.
# LOW-TIER-BEGIN: tests/mid/test_mid_process_groups.py::ProcessGroupTests.test_same_owner_requires_pid_and_start_time_with_two_second_tolerance
# Reason: Repeats process-table selection predicates or configured mock kill outcomes. The retained top-tier wrong/reused-owner refusal and real descendant shutdown cases provide the distinct safety/cleanup evidence. Case reviewed: Same owner requires pid and start time with two second tolerance.
# Source: arbol-codex-driver@0c596c5960c34039bd48d05df9b66b4ea9f31680:tests/mid/test_mid_process_groups.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     def test_same_owner_requires_pid_and_start_time_with_two_second_tolerance(self) -> None:
#         self.assertTrue(same_owner(owner(10, 1002), owner(10)))
#         self.assertFalse(same_owner(owner(11), owner(10)))
#         self.assertFalse(same_owner(owner(10, 1002.001), owner(10)))
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_process_groups.py::ProcessGroupTests.test_reused_group_leader_is_never_selected
# Reason: Repeats process-table selection predicates or configured mock kill outcomes. The retained top-tier wrong/reused-owner refusal and real descendant shutdown cases provide the distinct safety/cleanup evidence. Case reviewed: Reused group leader is never selected.
# Source: arbol-codex-driver@0c596c5960c34039bd48d05df9b66b4ea9f31680:tests/mid/test_mid_process_groups.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     def test_reused_group_leader_is_never_selected(self) -> None:
#         table = [row(10, 10, started=1005), row(11, 10, parent=10)]
#         self.assertEqual(surviving_process_groups([owner(10)], table), [])
#         self.assertEqual(descendant_process_groups(owner(10), table), [])
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_process_groups.py::ProcessGroupTests.test_live_leader_in_another_group_is_never_selected
# Reason: Repeats process-table selection predicates or configured mock kill outcomes. The retained top-tier wrong/reused-owner refusal and real descendant shutdown cases provide the distinct safety/cleanup evidence. Case reviewed: Live leader in another group is never selected.
# Source: arbol-codex-driver@0c596c5960c34039bd48d05df9b66b4ea9f31680:tests/mid/test_mid_process_groups.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     def test_live_leader_in_another_group_is_never_selected(self) -> None:
#         table = [row(10, 20), row(11, 10, parent=10)]
#         self.assertEqual(surviving_process_groups([owner(10)], table), [])
#         self.assertEqual(descendant_process_groups(owner(10), table), [])
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_process_groups.py::ProcessGroupTests.test_departed_leader_keeps_its_surviving_members_owned
# Reason: Repeats process-table selection predicates or configured mock kill outcomes. The retained top-tier wrong/reused-owner refusal and real descendant shutdown cases provide the distinct safety/cleanup evidence. Case reviewed: Departed leader keeps its surviving members owned.
# Source: arbol-codex-driver@0c596c5960c34039bd48d05df9b66b4ea9f31680:tests/mid/test_mid_process_groups.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     def test_departed_leader_keeps_its_surviving_members_owned(self) -> None:
#         table = [row(11, 10)]
#         self.assertEqual(surviving_process_groups([owner(10)], table), [owner(10)])
#         self.assertEqual(descendant_process_groups(owner(10), table), [owner(10)])
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_process_groups.py::ProcessGroupTests.test_departed_leader_without_members_is_finished
# Reason: Repeats process-table selection predicates or configured mock kill outcomes. The retained top-tier wrong/reused-owner refusal and real descendant shutdown cases provide the distinct safety/cleanup evidence. Case reviewed: Departed leader without members is finished.
# Source: arbol-codex-driver@0c596c5960c34039bd48d05df9b66b4ea9f31680:tests/mid/test_mid_process_groups.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     def test_departed_leader_without_members_is_finished(self) -> None:
#         table = [row(20, 20)]
#         self.assertEqual(surviving_process_groups([owner(10)], table), [])
#         self.assertEqual(descendant_process_groups(owner(10), table), [])
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_process_groups.py::ProcessGroupTests.test_zombie_only_group_is_finished
# Reason: Repeats process-table selection predicates or configured mock kill outcomes. The retained top-tier wrong/reused-owner refusal and real descendant shutdown cases provide the distinct safety/cleanup evidence. Case reviewed: Zombie only group is finished.
# Source: arbol-codex-driver@0c596c5960c34039bd48d05df9b66b4ea9f31680:tests/mid/test_mid_process_groups.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     def test_zombie_only_group_is_finished(self) -> None:
#         table = [row(10, 10, zombie=True), row(11, 10, parent=10, zombie=True)]
#         self.assertEqual(surviving_process_groups([owner(10)], table), [])
#         self.assertEqual(descendant_process_groups(owner(10), table), [])
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_process_groups.py::ProcessGroupTests.test_verified_group_collects_nested_descendants_and_separate_groups
# Reason: Repeats process-table selection predicates or configured mock kill outcomes. The retained top-tier wrong/reused-owner refusal and real descendant shutdown cases provide the distinct safety/cleanup evidence. Case reviewed: Verified group collects nested descendants and separate groups.
# Source: arbol-codex-driver@0c596c5960c34039bd48d05df9b66b4ea9f31680:tests/mid/test_mid_process_groups.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
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
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_process_groups.py::ProcessGroupTests.test_duplicate_owners_are_signalled_only_once
# Reason: Repeats process-table selection predicates or configured mock kill outcomes. The retained top-tier wrong/reused-owner refusal and real descendant shutdown cases provide the distinct safety/cleanup evidence. Case reviewed: Duplicate owners are signalled only once.
# Source: arbol-codex-driver@0c596c5960c34039bd48d05df9b66b4ea9f31680:tests/mid/test_mid_process_groups.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     def test_duplicate_owners_are_signalled_only_once(self) -> None:
#         table = [row(10, 10)]
#         self.assertEqual(surviving_process_groups([owner(10), owner(10)], table), [owner(10)])
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_process_groups.py::ForcedProcessGroupTests.test_immediate_kill_requires_fresh_snapshot_and_surviving_member
# Reason: Repeats process-table selection predicates or configured mock kill outcomes. The retained top-tier wrong/reused-owner refusal and real descendant shutdown cases provide the distinct safety/cleanup evidence. Case reviewed: Immediate kill requires fresh snapshot and surviving member.
# Source: arbol-codex-driver@0c596c5960c34039bd48d05df9b66b4ea9f31680:tests/mid/test_mid_process_groups.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
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
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_process_groups.py::ForcedProcessGroupTests.test_a_group_that_is_ending_may_answer_eperm
# Reason: Repeats process-table selection predicates or configured mock kill outcomes. The retained top-tier wrong/reused-owner refusal and real descendant shutdown cases provide the distinct safety/cleanup evidence. Case reviewed: A group that is ending may answer eperm.
# Source: arbol-codex-driver@0c596c5960c34039bd48d05df9b66b4ea9f31680:tests/mid/test_mid_process_groups.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
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
# LOW-TIER-SOURCE-END
# LOW-TIER-END
