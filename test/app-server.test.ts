import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { TestContext } from 'node:test';
import { mkdtemp, mkdir, readFile, realpath, rm, stat, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { AppServer, DRIVER_CONFIG, validateDriverConfig } from '../src/app-server.js';
import { Failure } from '../src/errors.js';
import { ownerAlive, processOwner } from '../src/state.js';
import type { Owner } from '../src/state.js';
import { quote } from './helpers.js';

const config = { config: { check_for_update_on_startup: false, web_search: 'live', cli_auth_credentials_store: 'file', analytics: { enabled: false }, features: { memories: false } } };
async function fake(t: TestContext, scenario = 'normal') {
  const directory = await mkdtemp(join(tmpdir(), 'codex-rpc-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const home = join(directory, 'subscription', 'home');
  const ownerHome = join(directory, 'owner');
  await mkdir(ownerHome);
  const script = join(directory, 'fake.mjs');
  const program = join(directory, 'codex');
  await writeFile(script, `
import { appendFileSync } from 'node:fs';
import { createInterface } from 'node:readline';
import { spawn } from 'node:child_process';
const scenario = ${JSON.stringify(scenario)};
const log = ${JSON.stringify(join(directory, 'received.jsonl'))};
appendFileSync(log, JSON.stringify({env:process.env,cwd:process.cwd()})+'\\n');
const config = ${JSON.stringify(config)};
const send = value => process.stdout.write(JSON.stringify(value)+'\\n');
let unknownRequest;
createInterface({input:process.stdin}).on('line',line=>{
  const value=JSON.parse(line); appendFileSync(log,JSON.stringify(value)+'\\n');
  if (value.id==='server-id') { send({id:unknownRequest,result:value.error}); return; }
  if (value.method==='initialize') {
    if(scenario==='hang-initialize')return;
    send({id:value.id,result:{codexHome:scenario==='wrong-home'?'${'/wrong/home'}':process.env.CODEX_HOME}}); return;
  }
  if(value.method==='config/read'){ send({id:value.id,result:scenario==='wrong-config'?{config:{}}:config}); return; }
  if(value.method==='early'){
    send({method:'account/login/completed',params:{loginId:'other',success:false}});
    send({method:'account/login/completed',params:{loginId:'wanted',success:true}});
    send({id:value.id,result:{ok:true}}); return;
  }
  if(value.method==='fragmented'){
    const bytes=Buffer.from(JSON.stringify({id:value.id,result:{text:'café🌲'}})+'\\n');
    const split=bytes.indexOf(Buffer.from('🌲'))+1;
    process.stdout.write(bytes.subarray(0,split)); setTimeout(()=>process.stdout.write(bytes.subarray(split)),5); return;
  }
  if(value.method==='unknown'){
    unknownRequest=value.id; send({id:'server-id',method:'future/request',params:{}}); return;
  }
  if(value.method==='malformed'){process.stdout.write('{bad json\\n');return;}
  if(value.method==='rpc-error'){send({id:value.id,error:{code:-32600,message:'codex account authentication required to read rate limits'}});return;}
  if(value.method==='structured-error'){send({id:value.id,error:{code:-32600,message:'Rejected',data:{httpStatusCode:403}}});return;}
  if(value.method==='unknown-error'){send({id:value.id,error:{code:-32600,message:'unknown identifier unauthorized-401'}});return;}
  if(value.method==='hang')return;
  if(value.method==='exit'){process.exit(3);return;}
  if(value.method==='spawn-child'){
    const child=spawn(process.execPath,['-e',"process.on('SIGTERM',()=>{});setInterval(()=>{},1000)"],{stdio:'inherit'});
    send({id:value.id,result:{pid:child.pid}});return;
  }
  if(value.id!==undefined)send({id:value.id,result:{ok:true}});
});
`);
  await writeFile(program, `#!/bin/sh\nexec ${quote(process.execPath)} ${quote(script)} "$@"\n`, { mode: 0o700 });
  const env = { HOME: ownerHome, PATH: '/usr/bin:/bin', LANG: 'C', TMPDIR: directory, OPENAI_API_KEY: 'do-not-inherit', CODEX_TOKEN: 'do-not-inherit', CODEX_HOME: '/wrong', ARBOL_OTHER: 'do-not-inherit' };
  return { home, directory, ownerHome, options: { toolPath: program, home, env, requestTimeoutMs: 1000 } };
}

test('app-server.home uses the private Subscription home and Driver configuration with a clean environment', async t => {
  const f = await fake(t);
  let spawned: Owner | undefined;
  const server = await AppServer.start({ ...f.options, onSpawn: owner => { spawned = owner; } });
  t.after(() => server.close());
  assert.deepEqual(server.owner, spawned);
  assert.equal(await ownerAlive(server.owner), true);
  const records = (await readFile(join(f.directory, 'received.jsonl'), 'utf8')).trim().split('\n').map(line => JSON.parse(line));
  assert.equal(records[0].env.HOME, f.ownerHome);
  assert.equal(records[0].env.CODEX_HOME, f.home);
  assert.equal(records[0].env.OPENAI_API_KEY, undefined);
  assert.equal(records[0].env.CODEX_TOKEN, undefined);
  assert.equal(records[0].env.ARBOL_OTHER, undefined);
  assert.equal(records[0].cwd, await realpath(f.home));
  assert.deepEqual(records.slice(1).map(value => value.method), ['initialize', 'initialized', 'config/read']);
  assert.equal(records[1].params.clientInfo.name, 'arbol-codex-driver');
  assert.equal(await readFile(join(f.home, 'config.toml'), 'utf8'), DRIVER_CONFIG);
  assert.equal((await stat(f.home)).mode & 0o777, 0o700);
  assert.equal((await stat(join(f.home, 'config.toml'))).mode & 0o777, 0o600);
  await server.close();
  assert.equal(await ownerAlive(server.owner), false);
});

test('app-server.notifications decodes fragmented JSONL and UTF-8 and retains early notifications for the matching waiter', async t => {
  const f = await fake(t);
  const server = await AppServer.start(f.options);
  t.after(() => server.close());
  assert.deepEqual(await server.request('fragmented', {}), { text: 'café🌲' });
  await server.request('early', {});
  assert.deepEqual(await server.waitForNotification<{loginId: string; success: boolean}>('account/login/completed', params => params.loginId === 'wanted'), { loginId: 'wanted', success: true });
  assert.deepEqual(await server.waitForNotification('account/login/completed'), { loginId: 'other', success: false });
  const waiting = server.waitForNotification<{loginId: string}>('account/login/completed', params => params.loginId === 'wanted');
  await server.request('early', {});
  assert.equal((await waiting).loginId, 'wanted');
});

test('app-server.unknown-request answers unknown tool requests with a JSON-RPC error', async t => {
  const f = await fake(t);
  const server = await AppServer.start(f.options);
  t.after(() => server.close());
  assert.deepEqual(await server.request('unknown', {}), { code: -32601, message: 'Method not supported by the Driver.' });
});

test('app-server.validation stops children with mismatched homes or ignored configuration', async t => {
  for (const scenario of ['wrong-home', 'wrong-config']) {
    const f = await fake(t, scenario);
    let owner: Owner | undefined;
    await assert.rejects(AppServer.start({ ...f.options, onSpawn: value => { owner = value; } }), Failure);
    assert.ok(owner);
    assert.equal(await ownerAlive(owner), false);
  }
  assert.throws(() => validateDriverConfig(null), Failure);
});

test('app-server.failures fails pending operations and cleans up on malformed data, exits and request timeouts', async t => {
  for (const method of ['malformed', 'exit', 'hang']) {
    const f = await fake(t);
    const server = await AppServer.start(f.options);
    t.after(() => server.close());
    await assert.rejects(server.request(method, {}, { timeoutMs: 50 }), error => error instanceof Failure && error.result.code === 'tool_failed');
    await server.close();
    assert.equal(await ownerAlive(server.owner), false);
  }
});

test('app-server.cancel leaves the transport available for account/login/cancel after cancelling requests and notifications', async t => {
  const f = await fake(t);
  const startup = new AbortController();
  const server = await AppServer.start({ ...f.options, signal: startup.signal });
  t.after(() => server.close());
  startup.abort();
  const abort = new AbortController();
  const request = server.request('hang', {}, { signal: abort.signal });
  const notice = server.waitForNotification('account/login/completed', () => true, { signal: abort.signal });
  abort.abort();
  await assert.rejects(request, /cancelled/);
  await assert.rejects(notice, /cancelled/);
  assert.deepEqual(await server.request('account/login/cancel', { loginId: 'wanted' }), { ok: true });
  await assert.rejects(server.waitForNotification('never', () => true, { timeoutMs: 10 }), /Timed out/);
});

test('app-server.start-cancel stops the spawned child on startup timeout or cancellation', async t => {
  for (const cancel of [false, true]) {
    const f = await fake(t, 'hang-initialize');
    let owner: Owner | undefined;
    const abort = new AbortController();
    const opening = AppServer.start({ ...f.options, requestTimeoutMs: 50, signal: abort.signal, onSpawn: value => { owner = value; if (cancel) abort.abort(); } });
    await assert.rejects(opening, Failure);
    assert.ok(owner);
    assert.equal(await ownerAlive(owner), false);
  }
});

test('app-server.rejection identifies authentication rejection from structured status or recorded wording and leaves unrelated errors as tool failures', async t => {
  const f = await fake(t);
  const server = await AppServer.start(f.options);
  t.after(() => server.close());
  await assert.rejects(server.request('rpc-error', {}), error => error instanceof Failure && error.result.code === 'credential_rejected' && error.result.detail?.basis === 'wording');
  await assert.rejects(server.request('structured-error', {}), error => error instanceof Failure && error.result.code === 'credential_rejected' && error.result.detail?.vendorStatus === 403);
  await assert.rejects(server.request('unknown-error', {}), error => error instanceof Failure && error.result.code === 'tool_failed');
});

test('app-server.descendants closes the process group including descendants that ignore SIGTERM', async t => {
  const f = await fake(t);
  const server = await AppServer.start(f.options);
  t.after(() => server.close());
  const { pid } = await server.request<{pid: number}>('spawn-child', {});
  const child = await processOwner(pid);
  assert.ok(child);
  await server.close();
  assert.equal(await ownerAlive(server.owner), false);
  // macOS can briefly retain a just-killed descendant before reaping it.
  for (let attempt = 0; attempt < 20 && await ownerAlive(child); attempt++) await new Promise(resolve => setTimeout(resolve, 10));
  assert.equal(await ownerAlive(child), false);
});
