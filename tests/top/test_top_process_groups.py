"""Individually selected top-tier cases. Shared fixtures retain their original paths."""
from __future__ import annotations

import test_process_groups as _support
from test_process_groups import (
    AsyncMock,
    force_process_groups,
    owner,
    patch,
    row,
    time,
)


class ForcedProcessGroupTests(_support.ForcedProcessGroupTests):
    async def test_immediate_kill_refuses_reused_or_wrong_group_leaders(self) -> None:
        for table in ([row(10, 10, started=1005)], [row(10, 20)]):
            with (
                self.subTest(table=table),
                patch("arbol_codex_driver.process_groups.process_snapshot", AsyncMock(return_value=table)),
                patch("arbol_codex_driver.process_groups.os.killpg") as kill,
            ):
                await force_process_groups([owner(10)], time.monotonic() + 1)
                kill.assert_not_called()
