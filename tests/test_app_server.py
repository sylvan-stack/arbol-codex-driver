import asyncio
import os
import shlex
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import cast
from unittest.mock import patch

from arbol_codex_driver.app_server import DRIVER_CONFIG, AppServer
from arbol_codex_driver.cancellation import Cancellation
from arbol_codex_driver.errors import Failure
from arbol_codex_driver.event_stream import EventStream, Output
from arbol_codex_driver.json_types import Json, Object, loads, object_value, utf8
from arbol_codex_driver.state import Owner, owner_alive, process_owner

FAKE = r"""
import json, os, signal, subprocess, sys, time
scenario, log = sys.argv[1:3]
def record(value):
    with open(log, 'a') as file: file.write(json.dumps(value)+'\n')
def send(value):
    sys.stdout.buffer.write((json.dumps(value, ensure_ascii=False)+'\n').encode()); sys.stdout.buffer.flush()
record({'env':dict(os.environ),'cwd':os.getcwd()})
config={'config':{'check_for_update_on_startup':False,'web_search':'live','cli_auth_credentials_store':'file','analytics':{'enabled':False},'features':{'memories':False}}}
unknown=None
if scenario.endswith('linger'): signal.signal(signal.SIGTERM, signal.SIG_IGN)
for line in sys.stdin:
    value=json.loads(line); record(value)
    method=value.get('method'); id_=value.get('id')
    if id_=='server-id': send({'id':unknown,'result':value.get('error')}); continue
    if method=='initialize':
        if scenario.startswith('hang-initialize'): continue
        version = '0.158.0' if scenario=='old-handshake' else 'bad-version' if scenario=='bad-handshake' else '0.159.2'
        send({'id':id_,'result':{'codexHome':'/wrong/home' if scenario=='wrong-home' else os.environ['CODEX_HOME'], 'userAgent':'codex/'+version+' (Mac OS)'}}); continue
    if method=='config/read':
        if scenario.startswith('hang-config'): continue
        send({'id':id_,'result':{'config':{}} if scenario=='wrong-config' else config}); continue
    if method=='fragmented':
        raw=(json.dumps({'id':id_,'result':{'text':'café🌲'}},ensure_ascii=False)+'\n').encode()
        split=raw.index('🌲'.encode())+1
        sys.stdout.buffer.write(raw[:split]); sys.stdout.buffer.flush(); time.sleep(.005)
        sys.stdout.buffer.write(raw[split:]); sys.stdout.buffer.flush(); continue
    if method=='early':
        for login,success in [('other',False),('wanted',True)]: send({'method':'account/login/completed','params':{'loginId':login,'success':success}})
    elif method in ('burst','burst-first','overflow'):
        if method=='burst-first': send({'id':id_,'result':{'ok':True}})
        for seq in range(9000 if method=='overflow' else 5000 if method=='burst-first' else 600): send({'method':'fixture/delta','params':{'seq':seq}})
        if method=='burst-first': continue
    elif method=='exit-log':
        sys.stderr.buffer.write(('🌲'*20000+'diagnostic-sentinel').encode()); sys.stderr.buffer.flush(); sys.exit(3)
    elif method=='unknown':
        unknown=id_; send({'id':'server-id','method':'future/request','params':{}}); continue
    elif method=='malformed':
        sys.stdout.write('{bad json\n'); sys.stdout.flush(); continue
    elif method=='oversized':
        send({'id':id_,'result':'x'*(4*1024*1024+1)}); continue
    elif method=='boolean-id':
        send({'id':True,'result':{'wrong':True}}); continue
    elif method=='rpc-error':
        send({'id':id_,'error':{'code':-32600,'message':'codex account authentication required to read rate limits'}}); continue
    elif method=='structured-error':
        send({'id':id_,'error':{'code':-32600,'message':'Rejected','data':{'httpStatusCode':403}}}); continue
    elif method=='unknown-error':
        send({'id':id_,'error':{'code':-32600,'message':'unknown identifier unauthorized-401'}}); continue
    elif method=='hang': continue
    elif method=='exit': sys.exit(3)
    elif method=='spawn-child':
        child=subprocess.Popen([sys.executable,'-c','import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)'])
        send({'id':id_,'result':{'pid':child.pid}}); continue
    if id_ is not None: send({'id':id_,'result':{'ok':True}})
record({'stage':'stdinEOF'})
if scenario.endswith('linger'):
    while True: time.sleep(60)
"""


class AppServerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="codex-rpc-python-")
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        self.home = self.folder / "subscription/home"
        self.log = self.folder / "received.jsonl"
        self.env = {
            "HOME": str(self.folder / "owner"),
            "PATH": "/usr/bin:/bin",
            "LANG": "C",
            "TMPDIR": str(self.folder),
            "OPENAI_API_KEY": "do-not-inherit",
            "CODEX_TOKEN": "do-not-inherit",
            "CODEX_HOME": "/wrong",
            "ARBOL_OTHER": "do-not-inherit",
            "ARBOL_TEST_TIME_SCALE": "10",
        }
        self.servers: list[AppServer] = []

    def program(self, scenario: str = "normal") -> str:
        script = self.folder / (scenario + ".py")
        script.write_text(FAKE)
        program = self.folder / (scenario + "-codex")
        program.write_text(
            f"#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(str(script))} {shlex.quote(scenario)} {shlex.quote(str(self.log))}\n"
        )
        program.chmod(0o700)
        return str(program)

    async def start(self, scenario: str = "normal") -> AppServer:
        server = await AppServer.start(
            tool_path=self.program(scenario), home=self.home, env=self.env, request_timeout=0.5
        )
        self.servers.append(server)
        return server

    async def asyncTearDown(self) -> None:
        for server in self.servers:
            await server.close(force_at=time.monotonic() + 0.1)

    def records(self) -> list[Object]:
        return [object_value(loads(line)) for line in self.log.read_text().splitlines()]

    async def test_private_home_configuration_clean_environment_and_owner_cleanup(self) -> None:
        server = await self.start()
        self.assertTrue(await owner_alive(server.owner))
        records = self.records()
        env = object_value(records[0]["env"])
        self.assertEqual(env["HOME"], self.env["HOME"])
        self.assertEqual(env["CODEX_HOME"], str(self.home))
        self.assertNotIn("OPENAI_API_KEY", env)
        self.assertNotIn("CODEX_TOKEN", env)
        self.assertNotIn("ARBOL_OTHER", env)
        self.assertEqual(records[0]["cwd"], str(self.home.resolve()))
        self.assertEqual([record.get("method") for record in records[1:]], ["initialize", "initialized", "config/read"])
        self.assertEqual((self.home / "config.toml").read_text(), DRIVER_CONFIG)
        self.assertEqual(self.home.stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.home / "config.toml").stat().st_mode & 0o777, 0o600)
        await server.close()
        self.assertFalse(await owner_alive(server.owner))

    async def test_handshake_version_and_effective_configuration_are_enforced(self) -> None:
        for scenario, code in (("old-handshake", "tool_unsupported"), ("bad-handshake", "tool_failed"),
                               ("wrong-config", "tool_unsupported")):
            with self.subTest(scenario=scenario), self.assertRaises(Failure) as caught:
                await self.start(scenario)
            self.assertEqual(caught.exception.result["code"], code)
            if scenario == "old-handshake":
                self.assertEqual(object_value(caught.exception.result["detail"])["toolVersion"], "0.158.0")
                self.assertEqual(object_value(caught.exception.result["detail"])["neededVersion"], "0.159.2")

    async def test_fragmented_utf8_early_notifications_burst_and_unknown_request(self) -> None:
        server = await self.start()
        self.assertEqual(await server.request("fragmented", {}), {"text": "café🌲"})
        await server.request("early", {})
        self.assertEqual(
            await server.wait_for_notification(
                "account/login/completed", lambda value: object_value(value).get("loginId") == "wanted"
            ),
            {"loginId": "wanted", "success": True},
        )
        self.assertEqual(
            await server.wait_for_notification("account/login/completed"), {"loginId": "other", "success": False}
        )
        await server.request("burst", {})
        for seq in range(600):
            notice = await server.next_notification()
            self.assertEqual((notice.method, notice.params), ("fixture/delta", {"seq": seq}))
        self.assertEqual(
            await server.request("unknown", {}), {"code": -32601, "message": "Method not supported by the Driver."}
        )

    async def test_malformed_oversized_boolean_id_exit_and_internal_request_timeout(self) -> None:
        for method in ("malformed", "oversized", "boolean-id", "exit", "hang", "overflow"):
            server = await self.start()
            with self.subTest(method=method), self.assertRaises(Failure) as caught:
                await server.request(method, {}, timeout=0.15)
            self.assertEqual(caught.exception.result["code"], "tool_failed")
            await server.close(force_at=time.monotonic() + 0.1)
            self.assertFalse(await owner_alive(server.owner))

    async def test_cancelled_request_leaves_transport_available_and_preabort_sends_nothing(self) -> None:
        server = await self.start()
        cancellation = Cancellation()
        pending = asyncio.create_task(server.request("hang", {}, cancellation=cancellation))
        waiting = asyncio.create_task(server.wait_for_notification("never", cancellation=cancellation))
        await asyncio.sleep(0.02)
        cancellation.abort()
        for task in (pending, waiting):
            with self.assertRaises(Failure):
                await task
        count = len(self.records())
        with self.assertRaises(Failure):
            await server.request("pre-aborted", {}, cancellation=cancellation)
        self.assertEqual(len(self.records()), count)
        self.assertEqual(await server.request("account/login/cancel", {}), {"ok": True})

    async def test_timeout_and_cancellation_include_blocked_stdin_drain(self) -> None:
        server = await self.start()
        blocked = asyncio.Event()
        with patch.object(server.child.stdin, "drain", side_effect=blocked.wait):
            before = time.monotonic()
            with self.assertRaises(Failure) as caught:
                await server.request("hang", {}, timeout=0.03)
            self.assertIn("request timeout", str(caught.exception))
            self.assertLess(time.monotonic() - before, 0.3)
        await server.close(force_at=time.monotonic() + 0.1)
        server = await self.start()
        cancellation = Cancellation()
        with patch.object(server.child.stdin, "drain", side_effect=blocked.wait):
            task = asyncio.create_task(server.request("hang", {}, cancellation=cancellation))
            await asyncio.sleep(0.02)
            cancellation.abort()
            with self.assertRaises(Failure):
                await asyncio.wait_for(task, 0.3)

    async def test_startup_wrong_home_config_and_cancellation_gives_eof_before_force(self) -> None:
        for scenario in ("wrong-home", "wrong-config", "hang-initialize-linger", "hang-config-linger"):
            cancellation = Cancellation()
            owners: list[Owner] = []

            async def spawned(owner: Owner, owners: list[Owner] = owners) -> None:
                owners.append(owner)

            opening = asyncio.create_task(
                AppServer.start(
                    tool_path=self.program(scenario),
                    home=self.home,
                    env=self.env,
                    request_timeout=3,
                    cancellation=cancellation,
                    on_spawn=spawned,
                )
            )
            if scenario.startswith("hang"):
                method = "initialize" if scenario.startswith("hang-initialize") else "config/read"
                deadline = time.monotonic() + 2
                while not self.log.exists() or not any(record.get("method") == method for record in self.records()):
                    self.assertLess(time.monotonic(), deadline)
                    await asyncio.sleep(0.005)
                stopped = time.monotonic()
                cancellation.abort()
            with self.assertRaises(Failure):
                await opening
            self.assertTrue(owners)
            self.assertFalse(await owner_alive(owners[0]))
            if scenario.startswith("hang"):
                elapsed = time.monotonic() - stopped
                self.assertGreaterEqual(elapsed, 0.19)
                self.assertLess(elapsed, 0.7)
                self.assertTrue(any(record.get("stage") == "stdinEOF" for record in self.records()))
            self.log.unlink(missing_ok=True)

    async def test_authentication_rejection_is_specific_and_diagnostics_are_bounded(self) -> None:
        server = await self.start()
        for method, code in (
            ("rpc-error", "credential_rejected"),
            ("structured-error", "credential_rejected"),
            ("unknown-error", "tool_failed"),
        ):
            with self.assertRaises(Failure) as caught:
                await server.request(method, {})
            self.assertEqual(caught.exception.result["code"], code)
        with self.assertRaises(Failure) as caught:
            await server.request("exit-log", {})
        excerpt = str(object_value(caught.exception.result.get("detail")).get("excerpt", ""))
        self.assertTrue(excerpt.endswith("diagnostic-sentinel"))
        self.assertLessEqual(len(utf8(excerpt)), 1024)
        self.assertNotIn("�", excerpt)

    async def test_cleanup_survives_capture_failure_and_ends_ignoring_descendant(self) -> None:
        server = await self.start()
        pid = object_value(await server.request("spawn-child", {}))["pid"]
        child = await process_owner(cast(int, pid))
        assert child is not None
        with patch.object(server, "capture_process_groups", side_effect=Failure("internal", "capture failed")):
            with self.assertRaises(Failure):
                await server.end(force_at=time.monotonic() + 0.1)
        self.assertFalse(await owner_alive(server.owner))
        for _ in range(20):
            if not await owner_alive(child):
                break
            await asyncio.sleep(0.01)
        self.assertFalse(await owner_alive(child))
        self.servers.remove(server)

    async def test_predicate_errors_settle_only_affected_waiter(self) -> None:
        server = await self.start()

        def bad(value: Json) -> bool:
            raise ValueError("predicate")

        waiting = asyncio.create_task(server.wait_for_notification("account/login/completed", bad))
        await asyncio.sleep(0)
        await server.request("early", {})
        with self.assertRaises(ValueError):
            await waiting
        self.assertEqual((await server.next_notification()).params, {"loginId": "other", "success": False})
        self.assertIsNone(server.failure)

    async def test_notification_backpressure_preserves_long_stream_and_wakes_for_rpc(self) -> None:
        server = await self.start()
        await server.request("burst-first", {})
        await asyncio.sleep(0.08)
        self.assertLessEqual(len(server.notifications), 4096)
        self.assertGreater(len(server.notifications), 0)
        total = 0
        while total < 5000:
            notice = await server.next_notification(timeout=1)
            self.assertEqual(notice.params, {"seq": total})
            total += 1
        self.assertEqual(await server.request("ping", {}), {"ok": True})


class OutputTests(unittest.IsolatedAsyncioTestCase):
    async def test_serialized_output_gapless_events_lone_surrogates_and_cancelled_blocked_flush(self) -> None:
        read, write = os.pipe()
        output = Output(write)
        events = EventStream(output)
        try:
            events.emit("started")
            events.emit("text", {"text": "\ud800"})
            await events.finish()
            raw = os.read(read, 8192).decode()
            records = [object_value(loads(line)) for line in raw.splitlines()]
            self.assertEqual([record["seq"] for record in records], [1, 2, 3])
            self.assertEqual([record["type"] for record in records], ["started", "text", "finished"])
            events.emit("text", {"text": "late"})
            self.assertEqual(events.sequence, 3)
            blocked = EventStream(output)
            blocked.emit("text", {"text": "x" * (1024 * 1024)})
            cancellation = Cancellation()
            task = asyncio.create_task(blocked.flush(cancellation))
            await asyncio.sleep(0.02)
            cancellation.abort()
            with self.assertRaises(Failure):
                await asyncio.wait_for(task, 0.3)
            blocked.abandon()
            self.assertTrue(output.abandoned)
            await asyncio.gather(*blocked.tasks, return_exceptions=True)
        finally:
            output.abandon()
            os.close(read)

    async def test_broken_output_aborts_writer_and_text_mode_uses_node_unicode_replacement(self) -> None:
        read, write = os.pipe()
        output = Output(write)
        events = EventStream(output)
        events.text_only = True
        try:
            events.emit("text", {"text": "\ud800\ud83d\ude00"})
            await events.flush()
            self.assertEqual(os.read(read, 8192), "�😀".encode())
            os.close(read)
            stopped = asyncio.Event()
            output.on_error = stopped.set
            events.emit("text", {"text": "broken"})
            with self.assertRaises(BrokenPipeError):
                await events.flush()
            self.assertTrue(stopped.is_set())
        finally:
            output.abandon()
