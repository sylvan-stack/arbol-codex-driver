# Shared fixtures only; test bodies are in top/ and mid/. See TESTS.md.
import asyncio
import os
import shlex
import signal
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import Protocol, cast

from arbol_codex_driver.json_types import Object, loads, object_value
from arbol_codex_driver.state import Owner, owner_alive, process_owner

ROOT = Path(__file__).resolve().parent.parent
ENTRY = ROOT / "bin/arbol-codex-driver"


class ReaderTransport(Protocol):
    _transport: asyncio.ReadTransport


class Running:
    def __init__(self, child: asyncio.subprocess.Process) -> None:
        self.child = child
        self.events: list[Object] = []
        self.changed = asyncio.Event()
        self.reader = asyncio.create_task(self.read())
        assert child.stderr is not None
        self.stderr = asyncio.create_task(child.stderr.read())

    async def read(self) -> None:
        assert self.child.stdout is not None
        while raw := await self.child.stdout.readline():
            self.events.append(object_value(loads(raw.decode())))
            self.changed.set()
        self.changed.set()

    async def until(self, predicate: Callable[[list[Object]], bool]) -> None:
        async with asyncio.timeout(5):
            while not predicate(self.events):
                self.changed.clear()
                if self.child.returncode is not None:
                    raise AssertionError("Run ended before expected event: " + str(self.events))
                await self.changed.wait()

    async def done(self) -> tuple[int, bytes]:
        async with asyncio.timeout(6):
            code = await self.child.wait()
            await self.reader
            return code, await self.stderr

    async def control(self, text: str = '{"type":"stop"}\n') -> None:
        assert self.child.stdin is not None
        self.child.stdin.write(text.encode())
        await self.child.stdin.drain()


class Fixture(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="codex-lifecycle-python-")
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)
        self.tool = self.home / "tool"
        self.tool.mkdir()
        self.state = self.home / "state"
        self.log = self.tool / "received.jsonl"
        self.scenario("C10 success")
        program = self.tool / "codex"
        program.write_text(
            f'#!/bin/sh\nexec {shlex.quote(str(ENTRY))} dev stand-in {shlex.quote(str(self.tool))} -- "$@"\n'
        )
        program.chmod(0o700)
        (self.home / ".arbol").mkdir()
        (self.home / ".arbol/arbol-codex-driver.json").write_text('{"toolPath":' + str_repr(str(program)) + "}")
        self.env = {
            "HOME": str(self.home),
            "PATH": "/usr/bin:/bin",
            "LANG": "C",
            "TMPDIR": str(self.home),
            "ARBOL_TEST_TIME_SCALE": "10",
        }
        self.children: list[asyncio.subprocess.Process] = []
        self.owners: list[Owner] = []
        self.assertEqual((await self.invoke(["subscriptions", "sign-in", "chatgpt"]))[0], 0)

    def scenario(self, value: str) -> None:
        (self.tool / "scenario").write_text(value + "\n")
        self.log.unlink(missing_ok=True)

    async def asyncTearDown(self) -> None:
        for child in self.children:
            if child.returncode is None:
                child.kill()
            if child.stdout is not None:
                cast(ReaderTransport, child.stdout)._transport.close()
            if child.stdin is not None:
                child.stdin.close()
            await asyncio.wait_for(child.wait(), 2)
        for owner in self.owners:
            if await owner_alive(owner):
                try:
                    os.kill(owner["pid"], signal.SIGKILL)
                except ProcessLookupError:
                    pass

    async def invoke(self, args: list[str]) -> tuple[int, bytes, bytes]:
        child = await asyncio.create_subprocess_exec(
            str(ENTRY),
            *args,
            "--state-dir",
            str(self.state),
            env=self.env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        async with asyncio.timeout(6):
            output, error = await child.communicate()
        return child.returncode or 0, output, error

    async def start(
        self, id_: str, control: bool = True, extra: list[str] | None = None, read: bool = True
    ) -> Running | asyncio.subprocess.Process:
        args = [
            "run",
            "--state-dir",
            str(self.state),
            "--run-id",
            id_,
            "--subscription",
            "chatgpt",
            "--tools",
            "all",
            "--cwd",
            str(self.home),
            *(["--control"] if control else []),
            *(extra if extra is not None else ["answer"]),
        ]
        child = await asyncio.create_subprocess_exec(
            str(ENTRY),
            *args,
            env=self.env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=512 * 1024 if read else 4096,
        )
        self.children.append(child)
        return Running(child) if read else child

    def records(self) -> list[Object]:
        if not self.log.exists():
            return []
        return [object_value(loads(raw)) for raw in self.log.read_text().splitlines() if raw]

    async def until_record(self, stage: str) -> Object:
        async with asyncio.timeout(5):
            while True:
                record = next((item for item in self.records() if item.get("stage") == stage), None)
                if record is not None:
                    return record
                await asyncio.sleep(0.005)

    async def workers(self) -> list[Owner]:
        checks = object_value((await self.until_record("input"))["checks"])
        owners: list[Owner] = []
        for name in ("toolPid", "shellPid", "backgroundPid"):
            owner = await process_owner(cast(int, checks[name]))
            self.assertIsNotNone(owner)
            assert owner is not None
            owners.append(owner)
        self.owners.extend(owners)
        return owners

    async def cleaned(self, id_: str, owners: list[Owner]) -> None:
        self.assertFalse((self.state / "runs" / (id_ + ".json")).exists())
        self.assertFalse((self.state / "tmp" / id_).exists())
        for owner in owners:
            self.assertFalse(await owner_alive(owner), str(owner))

    def final(self, events: list[Object], outcome: str = "cancelled") -> Object:
        self.assertTrue(events)
        self.assertEqual([event["seq"] for event in events], list(range(1, len(events) + 1)))
        self.assertEqual(sum(event["type"] == "finished" for event in events), 1)
        self.assertEqual(events[-1]["type"], "finished")
        self.assertEqual(events[-1]["outcome"], outcome)
        self.assertTrue(all(event["runId"] == events[0]["runId"] for event in events))
        for call in (event for event in events if event["type"] == "tool_started"):
            self.assertEqual(
                sum(event["type"] == "tool_finished" and event["callId"] == call["callId"] for event in events), 1
            )
        return events[-1]


class Lifecycle(Fixture):
    pass  # TEST-TIER-EMPTY-SUITE; helpers remain importable.


def str_repr(value: str) -> str:
    from arbol_codex_driver.json_types import dumps

    return dumps(value)

# Archived complete imports; restore needed names in their original scope, not at this file tail.
