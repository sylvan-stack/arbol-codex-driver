import asyncio
import os
import re
import signal
import subprocess
import time
from typing import cast

from .errors import Failure
from .json_types import timestamp
from .state import Owner, fixed_wait, ps_time


class ProcessSnapshot(Owner):
    parentId: int
    groupId: int
    zombie: bool


def same_owner(actual: Owner, expected: Owner) -> bool:
    return (
        actual["pid"] == expected["pid"]
        and abs(cast(float, timestamp(actual["startedAt"])) - cast(float, timestamp(expected["startedAt"]))) <= 2
    )


async def process_snapshot(deadline: float) -> list[ProcessSnapshot]:
    def query() -> list[ProcessSnapshot]:
        result = subprocess.run(
            ["/bin/ps", "-axo", "pid=,ppid=,pgid=,stat=,lstart="],
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "TZ": "UTC"},
            capture_output=True,
            text=True,
            timeout=max(0.001, min(1, deadline - time.monotonic())),
            check=True,
        )
        table: list[ProcessSnapshot] = []
        for line in result.stdout.splitlines():
            if not line.strip():
                continue
            row = re.fullmatch(r"\s*(\d+)\s+(\d+)\s+(\d+)\s+(\S+)\s+(.+?)\s*", line)
            if row is None:
                raise Failure("internal", "Cannot read the process table for run cleanup.")
            table.append(
                {
                    "pid": int(row[1]),
                    "parentId": int(row[2]),
                    "groupId": int(row[3]),
                    "zombie": row[4].startswith("Z"),
                    "startedAt": ps_time(row[5]),
                }
            )
        return table

    return await asyncio.to_thread(query)


def surviving_process_groups(owners: list[Owner], table: list[ProcessSnapshot]) -> list[Owner]:
    result: list[Owner] = []
    seen: set[int] = set()
    for owner in owners:
        if owner["pid"] in seen:
            continue
        seen.add(owner["pid"])
        leader = next((row for row in table if row["pid"] == owner["pid"]), None)
        if leader is not None and (not same_owner(leader, owner) or leader["groupId"] != owner["pid"]):
            continue
        if any(row["groupId"] == owner["pid"] and not row["zombie"] for row in table):
            result.append(owner)
    return result


def descendant_process_groups(owner: Owner, table: list[ProcessSnapshot]) -> list[Owner]:
    leader = next((row for row in table if row["pid"] == owner["pid"]), None)
    if leader is not None and (not same_owner(leader, owner) or leader["groupId"] != owner["pid"]):
        return []
    initial = (
        [row for row in table if row["groupId"] == owner["pid"]]
        if leader is not None or surviving_process_groups([owner], table)
        else []
    )
    if not initial:
        return []
    descendants = {row["pid"] for row in initial}
    previous: set[int] = set()
    while previous != descendants:
        previous = descendants.copy()
        descendants.update(row["pid"] for row in table if row["parentId"] in descendants)
    groups = dict.fromkeys(row["groupId"] for row in table if row["pid"] in descendants and not row["zombie"])
    result: list[Owner] = []
    for group in groups:
        row = next((row for row in table if row["pid"] == group), None)
        if row is not None:
            result.append({"pid": row["pid"], "startedAt": row["startedAt"]})
        elif group == owner["pid"]:
            result.append(owner.copy())
    return result


async def collect_process_groups(owner: Owner) -> list[Owner]:
    return descendant_process_groups(owner, await process_snapshot(time.monotonic() + 1))


# A group signalled with os.killpg may answer EPERM on macOS when its processes have exited but are not
# yet reaped: it is ending, as with ProcessLookupError, and the next process snapshot shows one that remains.


async def force_process_groups(owners: list[Owner], deadline: float) -> None:
    table = await process_snapshot(deadline)
    for owner in surviving_process_groups(owners, table):
        try:
            os.killpg(owner["pid"], signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


async def end_process_groups(
    owners: list[Owner], deadline: float | None = None, force_at: float | None = None
) -> list[Owner]:
    deadline = deadline if deadline is not None else time.monotonic() + fixed_wait(10000)
    force_at = min(deadline, force_at if force_at is not None else time.monotonic() + fixed_wait(2000))
    known = {owner["pid"]: owner for owner in owners}
    remaining = list(known.values())
    terminated: set[int] = set()
    while known and time.monotonic() < deadline:
        try:
            table = await process_snapshot(deadline)
        except (OSError, subprocess.SubprocessError):
            if time.monotonic() >= deadline:
                return remaining
            raise
        remaining = surviving_process_groups(list(known.values()), table)
        for owner in remaining:
            for child in descendant_process_groups(owner, table):
                known.setdefault(child["pid"], child)
        remaining = surviving_process_groups(list(known.values()), table)
        if not remaining:
            return []
        for owner in remaining:
            forced = time.monotonic() >= force_at
            if not forced and owner["pid"] in terminated:
                continue
            try:
                os.killpg(owner["pid"], signal.SIGKILL if forced else signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
            terminated.add(owner["pid"])
        await asyncio.sleep(min(fixed_wait(50), max(0.001, deadline - time.monotonic())))
    return remaining
