import asyncio
import os
import shlex
import signal
import tempfile
import time
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import Protocol, cast

from arbol_codex_driver.json_types import Json, Object, loads, object_value
from arbol_codex_driver.state import Owner, owner_alive, parse_owner, process_owner

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
    async def test_control_signals_eof_and_peer_stop_interrupt_once_then_cleanup(self) -> None:
        for path in ("control", "SIGINT", "SIGTERM", "EOF", "runs-stop"):
            with self.subTest(path=path):
                self.scenario("C15 tool")
                id_ = "stop-" + path.lower()
                running = cast(Running, await self.start(id_, control=path != "runs-stop"))
                await running.until(lambda events: any(event["type"] == "tool_started" for event in events))
                owners = await self.workers()
                if path == "control":
                    await running.control('{"type":"stop"}\n{"type":"stop"}\n')
                elif path == "EOF":
                    assert running.child.stdin is not None
                    running.child.stdin.close()
                elif path == "runs-stop":
                    self.assertEqual(await self.invoke(["runs", "stop", id_]), (0, b"", b""))
                else:
                    running.child.send_signal(signal.SIGINT if path == "SIGINT" else signal.SIGTERM)
                self.assertEqual(await running.done(), (2, b""))
                ended = self.final(running.events)
                self.assertTrue(ended["producedOutput"])
                self.assertEqual(object_value(ended["usage"])["inputTokens"], 3)
                interrupts = [record for record in self.records() if record.get("stage") == "interrupt"]
                self.assertEqual(len(interrupts), 1)
                self.assertEqual(
                    object_value(interrupts[0]["request"])["params"],
                    {"threadId": "fixture-thread", "turnId": "fixture-turn"},
                )
                await self.cleaned(id_, owners)

    async def test_active_nested_and_late_discovered_children_are_interrupted_and_attributed(self) -> None:
        for part in (
            "subagent",
            "subagent-finished",
            "subagent-nested",
            "subagent-discovery",
            "subagent-collab",
            "subagent-collab-discovery",
        ):
            with self.subTest(part=part):
                self.scenario("C15 " + part)
                running = cast(Running, await self.start(part))
                expected = "fixture-grandcall" if part == "subagent-nested" else "fixture-subcall"
                discovery = part.endswith("discovery")

                def ready(events: list[Object], discovery: bool = discovery, expected: str = expected) -> bool:
                    return any(
                        event["type"] == "tool_started"
                        and (
                            event.get("name") in ("spawn_agent", "spawnAgent")
                            if discovery
                            else event.get("callId") == expected
                        )
                        for event in events
                    )

                await running.until(ready)
                owners = await self.workers()
                await running.control()
                self.assertEqual(await running.done(), (2, b""))
                ended = self.final(running.events)
                threads = sorted(
                    str(object_value(object_value(record["request"])["params"])["threadId"])
                    for record in self.records()
                    if record.get("stage") == "interrupt"
                )
                wanted = (
                    ["fixture-subagent-thread"]
                    if part == "subagent-finished"
                    else ["fixture-subagent-thread", "fixture-thread"]
                )
                if part == "subagent-nested":
                    wanted.append("fixture-grandchild-thread")
                self.assertEqual(threads, sorted(wanted))
                child_result = next(
                    event
                    for event in running.events
                    if event["type"] == "tool_finished" and event.get("callId") == "fixture-subcall"
                )
                self.assertTrue(child_result["interrupted"])
                self.assertEqual(
                    child_result["parentCallId"],
                    "fixture-spawn-call" if "collab" in part else "fixture-subagent-thread",
                )
                if part == "subagent-nested":
                    self.assertIn("fixture-grandcall", cast(list[Json], ended["unfinishedCalls"]))
                await self.cleaned(part, owners)

    async def test_accepted_turn_before_rpc_reply_is_interrupted(self) -> None:
        self.scenario("C15 turn-start-race")
        running = cast(Running, await self.start("accepted"))
        await self.until_record("accepted-turn")
        owners = await self.workers()
        await running.control()
        self.assertEqual(await running.done(), (2, b""))
        self.final(running.events)
        self.assertTrue(any(record.get("stage") == "interrupt" for record in self.records()))
        await self.cleaned("accepted", owners)

    async def test_main_completion_waits_for_late_child_and_closes_spawn_once(self) -> None:
        self.scenario("C15 subagent-late")
        running = cast(Running, await self.start("late"))
        await running.until(lambda events: any(event.get("callId") == "fixture-subcall" for event in events))
        owners = await self.workers()
        self.assertEqual(await running.done(), (0, b""))
        self.final(running.events, "completed")
        self.assertTrue(
            any(
                event.get("text") == "child-only" and event["type"] == "text" and event.get("parentCallId")
                for event in running.events
            )
        )
        self.assertTrue(
            next(
                event
                for event in running.events
                if event["type"] == "tool_finished" and event.get("callId") == "fixture-subcall"
            )["ok"]
        )
        await self.cleaned("late", owners)

    async def test_ignored_interrupt_and_stop_during_normal_eof_use_same_force_anchor(self) -> None:
        for part in ("stubborn", "linger"):
            with self.subTest(part=part):
                self.scenario("C15 " + part)
                running = cast(Running, await self.start(part))
                await running.until(lambda events: any(event["type"] == "tool_started" for event in events))
                owners = await self.workers()
                if part == "linger":
                    await self.until_record("stdinEOF")
                    await asyncio.sleep(0.03)
                stopped = time.monotonic()
                await running.control()
                self.assertEqual(await running.done(), (2, b""))
                elapsed = time.monotonic() - stopped
                self.assertGreaterEqual(elapsed, 0.18)
                self.assertLess(elapsed, 0.8)
                self.final(running.events)
                await self.cleaned(part, owners)

    async def test_pending_first_stdin_request_signal_and_eof_cancel_before_vendor(self) -> None:
        for path in ("signal", "eof"):
            with self.subTest(path=path):
                delay = 0.05
                while True:
                    self.log.unlink(missing_ok=True)
                    running = cast(Running, await self.start("first-" + path, extra=["--request", "-"]))
                    await asyncio.sleep(delay)
                    if path == "signal":
                        running.child.send_signal(signal.SIGTERM)
                    else:
                        assert running.child.stdin is not None
                        running.child.stdin.close()
                    status, stderr = await running.done()
                    # A signal that comes before Python has installed the Driver's handler ends the process at once
                    # (status -15). Such a start proves nothing about the Driver: start again and wait longer.
                    if path == "signal" and status == -signal.SIGTERM and delay < 2:
                        delay *= 2
                        continue
                    break
                self.assertEqual((status, stderr), (2, b""))
                self.final(running.events)
                self.assertEqual(len(running.events), 1)
                self.assertEqual(self.records(), [])

    async def test_broken_output_cancels_native_turn_and_cleans_workers(self) -> None:
        self.scenario("C15 tool")
        running = cast(Running, await self.start("broken"))
        await running.until(lambda events: any(event["type"] == "tool_started" for event in events))
        owners = await self.workers()
        running.reader.cancel()
        await asyncio.gather(running.reader, return_exceptions=True)
        assert running.child.stdout is not None
        transport = cast(ReaderTransport, running.child.stdout)._transport
        transport.close()
        # asyncio closes the pipe on its next turn. Wait for that, so that the Driver's answer to the control line
        # finds no reader; otherwise a busy machine lets that answer into the pipe and the Driver waits on.
        while getattr(transport, "_pipe", None) is not None:
            await asyncio.sleep(0)
        await running.control('{"type":"unknown"}\n')
        # A guard against a hang only: the Driver's own stop deadlines add up to almost 3 seconds at scale 10.
        self.assertEqual(await asyncio.wait_for(running.child.wait(), 10), 2)
        self.assertEqual(await running.stderr, b"")
        self.assertTrue(any(record.get("stage") == "interrupt" for record in self.records()))
        await self.cleaned("broken", owners)

    async def test_blocked_output_cleanup_and_final_deadline_for_signal_and_control(self) -> None:
        for path in ("signal", "control"):
            with self.subTest(path=path):
                self.scenario("C20 structure")
                child = cast(asyncio.subprocess.Process, await self.start("blocked-" + path, read=False))
                await self.until_record("input")
                await asyncio.sleep(0.15)
                self.assertIsNone(child.returncode)
                record = object_value(loads((self.state / "runs" / ("blocked-" + path + ".json")).read_text()))
                owner = parse_owner(record["tool"])
                self.owners.append(owner)
                self.assertTrue(await owner_alive(owner))
                stopped = time.monotonic()
                if path == "signal":
                    child.send_signal(signal.SIGTERM)
                else:
                    assert child.stdin is not None
                    child.stdin.write(b'{"type":"invalid"}\n{"type":"stop"}\n')
                    await child.stdin.drain()
                async with asyncio.timeout(1.2):
                    while await owner_alive(owner):
                        await asyncio.sleep(0.01)
                async with asyncio.timeout(3):
                    while child.returncode is None:
                        await asyncio.sleep(0.005)
                self.assertEqual(child.returncode, 2)
                self.assertLess(time.monotonic() - stopped, 2.8)
                assert child.stdout is not None and child.stderr is not None
                cast(ReaderTransport, child.stdout)._transport.close()
                self.assertEqual(await child.stderr.read(), b"")
                await self.cleaned("blocked-" + path, [owner])


def str_repr(value: str) -> str:
    from arbol_codex_driver.json_types import dumps

    return dumps(value)
