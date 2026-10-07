import assert from 'node:assert/strict';
import { execFile, spawn } from 'node:child_process';
import type { ChildProcess, ChildProcessWithoutNullStreams } from 'node:child_process';
import { access, mkdir, readFile, readdir, rm, stat, utimes, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { test } from 'node:test';
import type { TestContext } from 'node:test';
import { pathToFileURL } from 'node:url';
import { promisify } from 'node:util';
import { Chats, chatKey, digest } from '../src/continuity.js';
import { Failure } from '../src/errors.js';
import { collectProcessGroups, descendantProcessGroups, endProcessGroups, survivingProcessGroups } from '../src/process-groups.js';
import type { ProcessSnapshot } from '../src/process-groups.js';
import { Runs } from '../src/runs.js';
import type { RunRecord } from '../src/runs.js';
import { ownerAlive, processOwner, State, writeJson } from '../src/state.js';
import type { Owner } from '../src/state.js';
import { fixture, invoke } from './helpers.js';

const exec = promisify(execFile);
const dead: Owner = { pid: 2147483647, startedAt: '2000-01-01T00:00:00.000Z' };
const wait = (milliseconds: number): Promise<void> => new Promise(resolve => setTimeout(resolve, milliseconds));
async function ready(child: ChildProcessWithoutNullStreams): Promise<string> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('Test process did not start.')), 3000);
    child.stdout.once('data', data => { clearTimeout(timer); resolve(String(data).trim()); });
    child.once('error', error => { clearTimeout(timer); reject(error); });
  });
}
function cleanupChild(t: TestContext, child: ChildProcess, group = false): Promise<void> {
  const closed = new Promise<void>(resolve => child.once('close', () => resolve()));
  t.after(async () => {
    if (child.exitCode === null && child.signalCode === null) {
      try { process.kill(group ? -child.pid! : child.pid!, 'SIGKILL'); } catch { /* Already gone. */ }
    }
    await closed;
  });
  return closed;
}
async function stateFixture(t: TestContext): Promise<{ state: State; runs: Runs; directory: string }> {
  const f = await fixture(t), state = new State(f.state);
  await state.initialize();
  return { state, runs: new Runs(state), directory: f.home };
}
const record = (owner = dead, fields: Partial<RunRecord> = {}): RunRecord => ({
  runId: 'orphan', subscriptionId: 'chatgpt', owner, startedAt: '2026-10-07T00:00:00.000Z', ...fields,
});

test('stop.group-identity validates group leaders, finds departed leaders and captures descendant command groups', () => {
  const owner = { pid: 100, startedAt: '2026-10-07T00:00:00.000Z' };
  const row = (pid: number, parentId: number, groupId: number, fields: Partial<ProcessSnapshot> = {}): ProcessSnapshot =>
    ({ pid, parentId, groupId, startedAt: owner.startedAt, zombie: false, ...fields });
  const table = [row(100, 1, 100), row(101, 100, 100), row(200, 101, 200), row(201, 200, 200), row(300, 1, 300)];
  assert.deepEqual(descendantProcessGroups(owner, table).map(item => item.pid), [100, 200]);
  assert.deepEqual(survivingProcessGroups([owner], [row(101, 1, 100)]), [owner]);
  assert.deepEqual(descendantProcessGroups(owner, [row(101, 1, 100), row(200, 101, 200)]).map(item => item.pid), [100, 200]);
  const reused = [row(100, 1, 100, { startedAt: '2026-10-07T00:00:05.000Z' }), row(101, 100, 100)];
  assert.deepEqual(descendantProcessGroups(owner, reused), []);
  assert.deepEqual(survivingProcessGroups([owner], reused), []);
  assert.deepEqual(descendantProcessGroups(owner, [row(100, 1, 300)]), []);
  assert.deepEqual(survivingProcessGroups([owner], [row(100, 1, 300)]), []);
  assert.deepEqual(survivingProcessGroups([owner], [row(101, 1, 100, { zombie: true })]), []);
});

test('stop.process-groups ends real descendants in separate groups and escalates ignored termination', { timeout: 8000 }, async t => {
  const parent = spawn(process.execPath, ['-e', `
    const { spawn } = require('node:child_process');
    process.on('SIGTERM', () => {});
    const command = spawn(process.execPath, ['-e', 'process.on("SIGTERM", () => {}); setInterval(() => {}, 1000);'], { detached: true, stdio: 'ignore' });
    setTimeout(() => console.log(command.pid), 100); setInterval(() => {}, 1000);
  `], { detached: true, stdio: ['pipe', 'pipe', 'pipe'] });
  const parentClosed = cleanupChild(t, parent, true);
  const commandPid = Number(await ready(parent));
  t.after(() => { try { process.kill(-commandPid, 'SIGKILL'); } catch { /* Already gone. */ } });
  const owner = await processOwner(parent.pid!); assert.ok(owner);
  const groups = await collectProcessGroups(owner);
  assert.deepEqual(groups.map(item => item.pid).sort((a, b) => a - b), [parent.pid!, commandPid].sort((a, b) => a - b));
  const started = performance.now();
  assert.deepEqual(await endProcessGroups(groups, performance.now() + 4000), []);
  await parentClosed;
  assert.ok(performance.now() - started >= 1900);
  assert.deepEqual(await endProcessGroups(groups, performance.now() + 1000), []);
});

test('stop.recovery clears orphan tool trees and scratch after an owner is killed, using the launch ledger', { timeout: 8000 }, async t => {
  const { state, runs } = await stateFixture(t);
  const owner = spawn('/bin/sleep', ['60'], { stdio: 'ignore' });
  const ownerClosed = cleanupChild(t, owner);
  const ownerIdentity = await processOwner(owner.pid!); assert.ok(ownerIdentity);
  const tool = spawn(process.execPath, ['-e', `
    const { spawn } = require('node:child_process');
    const command = spawn('/bin/sleep', ['60'], { detached: true, stdio: 'ignore' });
    console.log(command.pid); setInterval(() => {}, 1000);
  `], { detached: true, stdio: ['pipe', 'pipe', 'pipe'] });
  const toolClosed = cleanupChild(t, tool, true);
  const commandPid = Number(await ready(tool));
  t.after(() => { try { process.kill(-commandPid, 'SIGKILL'); } catch { /* Already gone. */ } });
  const toolIdentity = await processOwner(tool.pid!); assert.ok(toolIdentity);
  const scratch = join(state.directory, 'tmp', 'orphan');
  await mkdir(scratch, { recursive: true });
  const { stdout } = await exec('/bin/ps', ['-p', String(tool.pid), '-o', 'lstart='], { env: { PATH: '/usr/bin:/bin', LC_ALL: 'C', TZ: 'UTC' } });
  await writeFile(join(scratch, 'tool-owner.txt'), String(tool.pid) + '\n' + stdout.trim() + '\n');
  await writeFile(join(scratch, 'image'), 'temporary image');
  await writeJson(runs.path('orphan'), record(ownerIdentity));
  owner.kill('SIGKILL'); await ownerClosed;
  assert.deepEqual(await runs.list(), []);
  await toolClosed;
  assert.deepEqual(await endProcessGroups([{ pid: commandPid, startedAt: toolIdentity.startedAt }], performance.now() + 1000), []);
  await assert.rejects(access(scratch), { code: 'ENOENT' });
  await assert.rejects(access(runs.path('orphan')), { code: 'ENOENT' });
});

test('stop.recovery preserves live scratch, newer continuity and a reused tool identity', async t => {
  const { state, runs } = await stateFixture(t);
  const owner = await processOwner(process.pid); assert.ok(owner);
  const key = chatKey('example-chat'), chats = new Chats(state);
  const map = chats.path('chatgpt', key);
  const entry = { chatSessionId: 'example-chat', conversation: 'newer', workingDirectory: state.directory,
    messages: 2, digest: digest('history'), systemPromptDigest: digest(''), writtenAt: new Date().toISOString() };
  await writeJson(map, entry);
  const live = record(owner, { runId: 'live' }), stale = record(dead, { tool: { ...owner, startedAt: dead.startedAt }, chatKey: key, continuedConversation: 'prior' });
  await writeJson(runs.path(live.runId), live); await writeJson(runs.path(stale.runId), stale);
  for (const id of ['live', 'orphan']) { await mkdir(join(state.directory, 'tmp', id), { recursive: true }); await writeFile(join(state.directory, 'tmp', id, 'scratch'), id); }
  assert.deepEqual(await runs.list(), [live]);
  assert.equal(await readFile(join(state.directory, 'tmp', 'live', 'scratch'), 'utf8'), 'live');
  assert.equal(await ownerAlive(owner), true);
  assert.deepEqual(await chats.entry('chatgpt', key), entry);
  await assert.rejects(access(join(state.directory, 'tmp', 'orphan')), { code: 'ENOENT' });
  await writeJson(map, { ...entry, conversation: 'prior' }); await writeJson(runs.path('orphan'), stale);
  assert.deepEqual(await runs.list(), [live]);
  assert.equal(await chats.entry('chatgpt', key), undefined);
});

test('stop.recovery concurrent callers elect one cleanup outside the Subscription lock and take over a dead election', { timeout: 8000 }, async t => {
  const { state, runs } = await stateFixture(t);
  const tool = spawn(process.execPath, ['-e', 'process.on("SIGTERM", () => {}); console.log("ready"); setInterval(() => {}, 1000);'],
    { detached: true, stdio: ['pipe', 'pipe', 'pipe'] });
  const toolClosed = cleanupChild(t, tool, true); await ready(tool);
  const toolOwner = await processOwner(tool.pid!); assert.ok(toolOwner);
  await writeJson(runs.path('orphan'), record(dead, { tool: toolOwner, cleanupOwner: dead }));
  const stateUrl = pathToFileURL(join(import.meta.dirname, '../src/state.js')).href;
  const runsUrl = pathToFileURL(join(import.meta.dirname, '../src/runs.js')).href;
  const worker = `import { State } from ${JSON.stringify(stateUrl)}; import { Runs } from ${JSON.stringify(runsUrl)}; console.log(JSON.stringify(await new Runs(new State(process.argv[1])).list()));`;
  const callers = Promise.all(Array.from({ length: 2 }, () => exec(process.execPath, ['--input-type=module', '-e', worker, state.directory], {
    env: { PATH: '/usr/bin:/bin', ARBOL_TEST_TIME_SCALE: '2' }, timeout: 5000,
  })));
  let elected = false;
  for (let i = 0; i < 100; i++) {
    const current = JSON.parse(await readFile(runs.path('orphan'), 'utf8')) as RunRecord;
    if (current.cleanupOwner && current.cleanupOwner.pid !== dead.pid) { elected = true; break; }
    await wait(5);
  }
  assert.equal(elected, true);
  const started = performance.now();
  await state.withSubscriptionLock('chatgpt', async () => { await writeJson(join(state.subscription('chatgpt'), 'record.json'), { changed: true }); });
  assert.ok(performance.now() - started < 500, 'Process teardown must leave the Subscription lock available.');
  for (const caller of await callers) assert.equal(caller.stdout, '[]\n');
  await toolClosed;
  assert.deepEqual(await readdir(join(state.directory, 'runs')), []);
  assert.equal(await readFile(join(state.subscription('chatgpt'), 'record.json'), 'utf8'), '{"changed":true}\n');
});

test('stop.recovery reads saved shell group owners after the tool leader has exited', async t => {
  const { state, runs } = await stateFixture(t);
  const command = spawn('/bin/sleep', ['60'], { detached: true, stdio: 'ignore' });
  const closed = cleanupChild(t, command, true);
  const commandOwner = await processOwner(command.pid!); assert.ok(commandOwner);
  await writeJson(join(state.directory, 'tmp', 'orphan', 'shell-owners.json'), [commandOwner]);
  await writeJson(runs.path('orphan'), record(dead, { tool: dead }));
  assert.deepEqual(await runs.list(), []); await closed;
  await assert.rejects(access(join(state.directory, 'tmp', 'orphan')), { code: 'ENOENT' });
});

test('stop.recovery malformed process ledgers retain the reservation and report no private contents', async t => {
  const { state, runs } = await stateFixture(t);
  await writeJson(runs.path('orphan'), record());
  const scratch = join(state.directory, 'tmp', 'orphan'); await mkdir(scratch, { recursive: true });
  for (const name of ['tool-owner.txt', 'shell-owners.json']) {
    await writeFile(join(scratch, name), 'private-secret-invalid-ledger');
    await assert.rejects(runs.list(), (error: unknown) => error instanceof Failure && error.result.code === 'internal' && !error.message.includes('private-secret'));
    assert.equal((JSON.parse(await readFile(runs.path('orphan'), 'utf8')) as RunRecord).cleanupOwner, undefined);
    assert.equal(await readFile(join(scratch, name), 'utf8'), 'private-secret-invalid-ledger');
    await rm(join(scratch, name));
  }
});

test('stop.unfinished-writes runs list and unknown stop clear only old Driver writes', async t => {
  const { state, runs } = await stateFixture(t);
  const old = join(state.directory, 'runs', '.write-old'), recent = join(state.directory, 'runs', '.write-recent');
  const vendor = join(state.subscription('chatgpt'), 'home', '.write-old');
  for (const path of [old, recent, vendor]) { await writeJson(path, { private: true }); }
  for (const path of [old, vendor]) await utimes(path, new Date(0), new Date(0));
  await runs.stop('unknown');
  await assert.rejects(stat(old), { code: 'ENOENT' });
  assert.equal((await stat(recent)).isFile(), true); assert.equal((await stat(vendor)).isFile(), true);
  await runs.stop('unknown'); assert.deepEqual(await runs.list(), []);
});

test('stop.recovery-failure preserves the new request identifier and labels before vendor startup', async t => {
  const f = await fixture(t);
  await writeJson(join(f.state, 'runs', 'orphan.json'), { runId: 'orphan', subscriptionId: 'chatgpt' });
  const result = await invoke(['run', '--state-dir', f.state, '--run-id', 'caller-id', '--label', 'request=42', 'hello'], f.env);
  assert.equal(result.code, 1); assert.equal(result.stderr, '');
  assert.equal(result.result.type, 'finished'); assert.equal(result.result.outcome, 'failed');
  assert.equal(result.result.error.code, 'internal'); assert.equal(result.result.runId, 'caller-id');
  assert.deepEqual(result.result.labels, { request: '42' });
  assert.equal(result.stdout.trim().split('\n').length, 1);
  await assert.rejects(access(join(f.tool, 'received.jsonl')), { code: 'ENOENT' });
});

test('runs.stop waits for its owner to remove the record and treats ended runs as stopped', async t => {
  const { state, runs, directory } = await stateFixture(t);
  const finished = join(directory, 'finished');
  const child = spawn(process.execPath, ['-e', `
    const fs = require('node:fs');
    process.on('SIGTERM', () => { fs.writeFileSync(process.argv[2], 'cancelled'); fs.unlinkSync(process.argv[1]); process.exit(0); });
    console.log('ready'); setInterval(() => {}, 1000);
  `, runs.path('orphan'), finished], { stdio: ['pipe', 'pipe', 'pipe'] });
  const closed = cleanupChild(t, child); await ready(child);
  const owner = await processOwner(child.pid!); assert.ok(owner);
  await writeJson(runs.path('orphan'), record(owner));
  await runs.stop('orphan'); await closed;
  assert.equal(await readFile(finished, 'utf8'), 'cancelled');
  await assert.rejects(access(runs.path('orphan')), { code: 'ENOENT' });
  await runs.stop('orphan'); assert.deepEqual(await new Runs(state).list(), []);
});

test('runs.stop leaves a replacement reservation alone and bounds a live owner that ignores termination', async t => {
  const { state, runs } = await stateFixture(t);
  const live = await processOwner(process.pid); assert.ok(live);
  const replacement = record(live, { startedAt: '2026-10-07T00:00:01.000Z' });
  const child = spawn(process.execPath, ['-e', `
    const fs = require('node:fs');
    process.on('SIGTERM', () => { fs.writeFileSync(process.argv[1] + '.next', process.argv[2]); fs.renameSync(process.argv[1] + '.next', process.argv[1]); });
    console.log('ready'); setInterval(() => {}, 1000);
  `, runs.path('orphan'), JSON.stringify(replacement)], { stdio: ['pipe', 'pipe', 'pipe'] });
  cleanupChild(t, child); await ready(child);
  const owner = await processOwner(child.pid!); assert.ok(owner);
  await writeJson(runs.path('orphan'), record(owner));
  await new Runs(state, { ARBOL_TEST_TIME_SCALE: '100' }).stop('orphan');
  assert.deepEqual(JSON.parse(await readFile(runs.path('orphan'), 'utf8')), replacement);
  assert.equal(await ownerAlive(owner), true);
  const stubborn = spawn(process.execPath, ['-e', 'process.on("SIGTERM", () => {}); console.log("ready"); setInterval(() => {}, 1000);'], { stdio: ['pipe', 'pipe', 'pipe'] });
  cleanupChild(t, stubborn); await ready(stubborn);
  const stubbornOwner = await processOwner(stubborn.pid!); assert.ok(stubbornOwner);
  await writeJson(runs.path('orphan'), record(stubbornOwner));
  const started = performance.now();
  await assert.rejects(new Runs(state, { ARBOL_TEST_TIME_SCALE: '100' }).stop('orphan'), (error: unknown) =>
    error instanceof Failure && error.result.code === 'in_use');
  assert.ok(performance.now() - started >= 200);
  assert.ok(performance.now() - started < 1500);
  assert.equal(await ownerAlive(stubbornOwner), true);
});

for (const operation of ['sign-out', 'remove'] as const) {
  test(`stop.subscription-force ${operation} recovers a dying owner through the run ledger before changing credentials`, { timeout: 8000 }, async t => {
    const f = await fixture(t);
    await writeFile(join(f.tool, 'scenario'), 'C5 success\n');
    const created = await invoke(['subscriptions', 'create', '--family', 'chatgpt', '--label', 'Work', '--id', 'work', '--state-dir', f.state], f.env);
    assert.equal(created.code, 0);
    const state = new State(f.state), runs = new Runs(state), chats = new Chats(state), key = chatKey('forced-chat');
    await writeJson(join(state.subscription('work'), 'record.json'), { ...created.result, settings: undefined, state: 'signed_in' });
    await writeJson(chats.path('work', key), { chatSessionId: 'forced-chat', conversation: 'continued', workingDirectory: f.home,
      messages: 2, digest: digest('history'), systemPromptDigest: digest(''), writtenAt: new Date().toISOString() });
    const owner = spawn(process.execPath, ['-e', 'process.on("SIGTERM", () => process.exit(0)); console.log("ready"); setInterval(() => {}, 1000);'],
      { stdio: ['pipe', 'pipe', 'pipe'] });
    const ownerClosed = cleanupChild(t, owner); await ready(owner);
    const ownerIdentity = await processOwner(owner.pid!); assert.ok(ownerIdentity);
    const shell = spawn('/bin/sleep', ['60'], { detached: true, stdio: 'ignore' });
    const shellClosed = cleanupChild(t, shell, true);
    const shellIdentity = await processOwner(shell.pid!); assert.ok(shellIdentity);
    await writeJson(join(state.directory, 'tmp', 'orphan', 'shell-owners.json'), [shellIdentity]);
    await writeJson(runs.path('orphan'), record(ownerIdentity, { subscriptionId: 'work', tool: dead, chatKey: key, continuedConversation: 'continued' }));
    // This owner dies on termination without deleting its record. Forced account
    // operations must use the same recovery as runs stop, including the ledger.
    const result = await exec(process.execPath, [join(import.meta.dirname, '../../bin/arbol-codex-driver.mjs'),
      'subscriptions', operation, 'work', '--force', '--state-dir', f.state], { env: f.env, timeout: 5000 });
    await ownerClosed; await shellClosed;
    await assert.rejects(access(runs.path('orphan')), { code: 'ENOENT' });
    await assert.rejects(access(join(state.directory, 'tmp', 'orphan')), { code: 'ENOENT' });
    assert.equal(await chats.entry('work', key), undefined);
    if (operation === 'sign-out') assert.equal(JSON.parse(result.stdout).state, 'signed_out');
    else assert.equal(result.stdout, '');
  });
}
