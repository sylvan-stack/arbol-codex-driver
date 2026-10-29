# Shared fixtures; case bodies live in top/ and mid/. See TESTS.md.
import os
from typing import cast

from arbol_codex_driver.app_server import DRIVER_CONFIG, AppServer
from arbol_codex_driver.event_stream import EventStream, Output
from arbol_codex_driver.json_types import Json, Object, loads, object_value, utf8
from arbol_codex_driver.state import Owner, owner_alive, process_owner

import asyncio
import shlex
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from arbol_codex_driver.app_server import AppServer
from arbol_codex_driver.cancellation import Cancellation
from arbol_codex_driver.errors import Failure
from arbol_codex_driver.json_types import Object, loads, object_value

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


class OutputTests(unittest.IsolatedAsyncioTestCase):
    pass  # TEST-TIER-EMPTY-SUITE; helpers remain importable.


# Archived complete imports; restore needed names in their original scope, not at this file tail.
