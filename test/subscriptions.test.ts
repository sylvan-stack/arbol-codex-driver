import { test } from 'node:test';
import type { TestContext } from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdir, readFile, readdir, stat, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { State, processOwner, writeJson } from '../src/state.js';
import type { ProcessEnv } from '../src/types.js';
import { cli, fixture, invoke, quote } from './helpers.js';

type Fixture = Awaited<ReturnType<typeof fixture>>;
interface Reply { code: number | null; stdout: string; stderr: string }
const recordPath = (f: Fixture, id: string): string => join(f.state, 'subscriptions', id, 'record.json');
const settingsFile = (f: Fixture): string => join(f.home, '.arbol', 'arbol-codex-driver.json');

function start(t: TestContext, args: string[], env: ProcessEnv) {
  const child = spawn(process.execPath, [cli, ...args], { env, stdio: ['ignore', 'pipe', 'pipe'] });
  let stdout = '', stderr = '';
  child.stdout.setEncoding('utf8'); child.stderr.setEncoding('utf8');
  child.stdout.on('data', text => { stdout += text; });
  child.stderr.on('data', text => { stderr += text; });
  const done = new Promise<Reply>((resolve, reject) => {
    const timer = setTimeout(() => { child.kill('SIGKILL'); reject(new Error('Subscription command did not finish.')); }, 10000);
    child.once('error', error => { clearTimeout(timer); reject(error); });
    child.once('close', code => { clearTimeout(timer); resolve({ code, stdout, stderr }); });
  });
  void done.catch(() => {});
  t.after(() => { if (child.exitCode === null && child.signalCode === null) child.kill('SIGKILL'); });
  return { child, done };
}

async function untilFile(path: string): Promise<void> {
  for (let attempt = 0; attempt < 400; attempt++) {
    try { await stat(path); return; }
    catch (error) { if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error; }
    await new Promise<void>(resolve => setTimeout(resolve, 5));
  }
  throw new Error('The synthetic account request did not start.');
}

async function create(f: Fixture, id: string) {
  const reply = await invoke(['subscriptions', 'create', '--family', 'chatgpt', '--label', 'Test account', '--id', id, '--state-dir', f.state], f.env);
  assert.equal(reply.code, 0, reply.stdout);
  return reply.result;
}

async function noVendor(f: Fixture): Promise<void> {
  await assert.rejects(stat(join(f.tool, 'received.jsonl')), { code: 'ENOENT' });
}

test('subscriptions.local exposes one implicit ChatGPT account without starting the tool', async t => {
  const f = await fixture(t);
  const families = await invoke(['subscriptions', 'families', '--state-dir', f.state], f.env);
  assert.equal(families.code, 0);
  assert.equal(families.result.length, 1);
  assert.equal(families.result[0].id, 'chatgpt'); assert.equal(families.result[0].auth, 'vendor_login');
  assert.equal(families.result[0].settings.type, 'object');
  assert.deepEqual(families.result[0].settings.properties, {});
  const first = await invoke(['subscriptions', 'list', '--state-dir', f.state], f.env);
  const second = await invoke(['subscriptions', 'list', '--state-dir', f.state], f.env);
  assert.equal(first.code, 0); assert.deepEqual(first.result, second.result);
  assert.equal(first.result.length, 1);
  assert.deepEqual([first.result[0].id, first.result[0].family, first.result[0].auth, first.result[0].state, first.result[0].settings],
    ['chatgpt', 'chatgpt', 'vendor_login', 'signed_out', {}]);
  assert.ok(Number.isFinite(Date.parse(first.result[0].createdAt)));
  assert.equal(first.result[0].updatedAt, first.result[0].createdAt);
  await assert.rejects(stat(recordPath(f, 'chatgpt')), { code: 'ENOENT' });
  await noVendor(f);
});

test('subscriptions.create reserves automatic identifiers across competing processes and keeps homes private', async t => {
  const f = await fixture(t);
  const args = ['subscriptions', 'create', '--family=chatgpt', '--label=Work', '--state-dir', f.state];
  const replies = await Promise.all(Array.from({ length: 4 }, () => invoke(args, f.env)));
  for (const reply of replies) assert.equal(reply.code, 0, reply.stdout);
  assert.deepEqual(replies.map(reply => reply.result.id).sort(), ['chatgpt-2', 'chatgpt-3', 'chatgpt-4', 'chatgpt-5']);
  const explicit = await create(f, 'work.chatgpt');
  assert.equal(explicit.family, 'chatgpt'); assert.equal(explicit.auth, 'vendor_login');
  assert.equal(explicit.state, 'signed_out'); assert.deepEqual(explicit.settings, {});
  for (const id of [...replies.map(reply => reply.result.id), explicit.id]) {
    const path = join(f.state, 'subscriptions', id);
    assert.equal((await stat(path)).mode & 0o777, 0o700);
    assert.equal((await stat(join(path, 'home'))).mode & 0o777, 0o700);
    assert.equal((await stat(recordPath(f, id))).mode & 0o777, 0o600);
    const stored = JSON.parse(await readFile(recordPath(f, id), 'utf8'));
    assert.equal('settings' in stored, false);
    assert.equal('secret' in stored, false);
    assert.ok(!(await readdir(path)).some(name => name === 'lock' || name.startsWith('.write-')));
  }
  await noVendor(f);
});

test('subscriptions.update changes the label while preserving account, usage, dates and owner settings', async t => {
  const f = await fixture(t);
  await create(f, 'work');
  const original = JSON.parse(await readFile(recordPath(f, 'work'), 'utf8'));
  const stored = { ...original, state: 'signed_in', account: { email: 'fixture@example.invalid', plan: 'pro' },
    checkedAt: '2026-10-06T00:00:00Z', lastUsage: { outcome: 'ok', fetchedAt: '2026-10-06T00:00:00Z', windows: [] } };
  await writeJson(recordPath(f, 'work'), stored);
  const settings = JSON.stringify({ toolPath: join(f.tool, 'codex'), subscriptions: { work: { defaultModel: 'fixture-model', defaultEffort: 'high' } } }, null, 2);
  await writeFile(settingsFile(f), settings);
  const changed = await invoke(['subscriptions', 'update', 'work', '--label', 'Renamed', '--state-dir', f.state], f.env);
  assert.equal(changed.code, 0); assert.equal(changed.result.label, 'Renamed');
  const next = JSON.parse(await readFile(recordPath(f, 'work'), 'utf8'));
  assert.deepEqual({ ...next, label: stored.label, updatedAt: stored.updatedAt }, stored);
  assert.equal(next.updatedAt, changed.result.updatedAt);
  const unchanged = await invoke(['subscriptions', 'update', 'work', '--state-dir', f.state], f.env);
  assert.equal(unchanged.code, 0); assert.deepEqual(unchanged.result, changed.result);
  assert.equal(await readFile(settingsFile(f), 'utf8'), settings);
  await noVendor(f);
});

test('subscriptions.settings ignores unknown family values and validates malformed settings before mutation', async t => {
  const f = await fixture(t);
  const text = JSON.stringify({ subscriptions: { chatgpt: { settings: { unknown: 'secret-sentinel' } } } });
  await writeFile(settingsFile(f), text);
  const listed = await invoke(['subscriptions', 'list', '--state-dir', f.state], f.env);
  assert.equal(listed.code, 0); assert.deepEqual(listed.result[0].settings, {});
  assert.equal(listed.stdout.includes('secret-sentinel'), false); assert.equal(listed.stderr, '');
  assert.equal(await readFile(settingsFile(f), 'utf8'), text);
  for (const bad of [{ defaultModel: 2 }, { defaultEffort: [] }, { settings: 'secret-sentinel' }, { settings: [] }]) {
    await writeFile(settingsFile(f), JSON.stringify({ subscriptions: { untouched: bad } }));
    const failed = await invoke(['subscriptions', 'create', '--family', 'chatgpt', '--label', 'Work', '--id', 'untouched', '--state-dir', f.state], f.env);
    assert.equal(failed.code, 1); assert.equal(failed.result.error.code, 'invalid_input');
    assert.equal(failed.stdout.includes('secret-sentinel'), false);
    await assert.rejects(stat(recordPath(f, 'untouched')), { code: 'ENOENT' });
  }
  await noVendor(f);
});

test('subscriptions.invalid rejects unknown families, unsafe names and duplicates without overwriting records', async t => {
  const f = await fixture(t);
  const created = await create(f, 'work');
  const before = await readFile(recordPath(f, 'work'), 'utf8');
  const args = [
    ['--family', 'unknown', '--label', 'Work'], ['--family', 'chatgpt'], ['--label', 'Work'],
    ...['../outside', '/absolute', '_leading', '-leading', 'with space', 'café', 'x'.repeat(129)]
      .map(id => ['--family', 'chatgpt', '--label', 'Work', `--id=${id}`]),
  ];
  for (const input of args) {
    const failed = await invoke(['subscriptions', 'create', ...input, '--state-dir', f.state], f.env);
    assert.equal(failed.code, 1, JSON.stringify(input)); assert.equal(failed.result.error.code, 'invalid_input');
  }
  for (const id of ['chatgpt', created.id]) {
    const failed = await invoke(['subscriptions', 'create', '--family', 'chatgpt', '--label', 'Duplicate', '--id', id, '--state-dir', f.state], f.env);
    assert.equal(failed.code, 1); assert.equal(failed.result.error.code, 'in_use');
  }
  for (const command of ['update', 'remove', 'check', 'models', 'usage']) {
    const failed = await invoke(['subscriptions', command, 'missing', '--state-dir', f.state], f.env);
    assert.equal(failed.code, 1); assert.equal(failed.result.error.code, 'not_found');
  }
  assert.equal(await readFile(recordPath(f, 'work'), 'utf8'), before);
  await noVendor(f);
});

test('subscriptions.remove deletes only the selected account and returns no document', async t => {
  const f = await fixture(t);
  await create(f, 'first'); await create(f, 'second');
  const second = await readFile(recordPath(f, 'second'), 'utf8');
  await writeFile(join(f.state, 'subscriptions', 'first', 'home', 'auth.json'), 'vendor-owned-secret');
  await mkdir(join(f.state, 'subscriptions', 'first', 'chats'));
  await writeFile(join(f.state, 'subscriptions', 'first', 'chats', 'history.json'), 'conversation');
  const removed = await start(t, ['subscriptions', 'remove', 'first', '--state-dir', f.state], f.env).done;
  assert.deepEqual(removed, { code: 0, stdout: '', stderr: '' });
  for (const entry of ['home', 'record.json', 'chats']) {
    await assert.rejects(stat(join(f.state, 'subscriptions', 'first', entry)), { code: 'ENOENT' });
  }
  assert.equal(await readFile(recordPath(f, 'second'), 'utf8'), second);
  const listed = await invoke(['subscriptions', 'list', '--state-dir', f.state], f.env);
  assert.deepEqual(listed.result.map((account: { id: string }) => account.id).sort(), ['chatgpt', 'second']);
  await noVendor(f);
});

test('subscriptions.refused checks unsigned state before probing the vendor tool', async t => {
  const f = await fixture(t);
  await writeFile(settingsFile(f), JSON.stringify({ toolPath: join(f.home, 'nonexistent-codex') }));
  for (const command of ['models', 'check']) {
    const failed = await invoke(['subscriptions', command, 'chatgpt', '--state-dir', f.state], f.env);
    assert.equal(failed.code, 1); assert.equal(failed.result.error.code, 'not_signed_in');
  }
  const usage = await invoke(['subscriptions', 'usage', 'chatgpt', '--state-dir', f.state], f.env);
  assert.equal(usage.code, 0); assert.equal(usage.result.outcome, 'needs_sign_in'); assert.deepEqual(usage.result.windows, []);
  await noVendor(f);
});

test('subscriptions.snapshots refuses malformed records without leaking their content', async t => {
  const f = await fixture(t);
  await create(f, 'work');
  const original = JSON.parse(await readFile(recordPath(f, 'work'), 'utf8'));
  const malformed = [
    { ...original, id: 'other' }, { ...original, family: 'openai-api' }, { ...original, auth: 'key' },
    { ...original, state: 'signing_in' }, { ...original, createdAt: 'secret-sentinel' },
    { ...original, state: 'needs_attention' }, { ...original, account: { email: 12 } },
    { ...original, lastUsage: { outcome: 'ok', fetchedAt: 'secret-sentinel', windows: [] } },
    { ...original, secret: 'secret-sentinel' },
  ];
  for (const value of malformed) {
    const content = JSON.stringify(value);
    await writeFile(recordPath(f, 'work'), content);
    const failed = await invoke(['subscriptions', 'list', '--state-dir', f.state], f.env);
    assert.equal(failed.code, 1); assert.equal(failed.result.error.code, 'internal');
    assert.equal(failed.stdout.includes('secret-sentinel'), false);
    assert.equal(await readFile(recordPath(f, 'work'), 'utf8'), content);
  }
  await writeFile(recordPath(f, 'work'), 'broken secret-sentinel');
  const failed = await invoke(['subscriptions', 'update', 'work', '--label', 'Renamed', '--state-dir', f.state], f.env);
  assert.equal(failed.code, 1); assert.equal(failed.result.error.code, 'internal');
  assert.equal(failed.stdout.includes('secret-sentinel'), false);
  await noVendor(f);
});

test('subscriptions.progress observes a live sign-in but recovers dead and reused owners', async t => {
  const f = await fixture(t);
  await create(f, 'work');
  const owner = await processOwner(process.pid); assert.ok(owner);
  const path = join(f.state, 'subscriptions', 'work', 'sign-in.json');
  const expiresAt = new Date(Date.now() + 300000).toISOString();
  await writeJson(path, { owner, operation: 'sign_in', expiresAt });
  const live = await invoke(['subscriptions', 'list', '--state-dir', f.state], f.env);
  assert.equal(live.code, 0);
  assert.equal(live.result.find((account: { id: string }) => account.id === 'work').state, 'signing_in');
  const relabelled = await invoke(['subscriptions', 'update', 'work', '--label', 'Pending', '--state-dir', f.state], f.env);
  assert.equal(relabelled.code, 0); assert.equal(relabelled.result.state, 'signing_in');
  assert.equal(JSON.parse(await readFile(recordPath(f, 'work'), 'utf8')).state, 'signed_out');
  for (const dead of [{ pid: 2147483647, startedAt: '2000-01-01T00:00:00Z' }, { pid: process.pid, startedAt: '2000-01-01T00:00:00Z' }]) {
    await writeJson(path, { owner: dead, operation: 'sign_in', expiresAt });
    const recovered = await invoke(['subscriptions', 'list', '--state-dir', f.state], f.env);
    assert.equal(recovered.code, 0);
    assert.equal(recovered.result.find((account: { id: string }) => account.id === 'work').state, 'signed_out');
    await assert.rejects(stat(path), { code: 'ENOENT' });
  }
  await writeJson(path, { owner: { pid: 'secret-sentinel', startedAt: owner.startedAt }, expiresAt });
  const failed = await invoke(['subscriptions', 'list', '--state-dir', f.state], f.env);
  assert.equal(failed.code, 1); assert.equal(failed.result.error.code, 'internal');
  assert.equal(failed.stdout.includes('secret-sentinel'), false);
  await noVendor(f);
});

test('subscriptions.independent mutations proceed while another account lock is held', async t => {
  const f = await fixture(t);
  await create(f, 'first'); await create(f, 'second');
  const state = new State(f.state);
  let release!: () => void, acquired!: () => void;
  const ready = new Promise<void>(resolve => { acquired = resolve; });
  const pending = state.withSubscriptionLock('first', async () => {
    acquired(); await new Promise<void>(resolve => { release = resolve; });
  });
  await ready;
  try {
    const changed = await invoke(['subscriptions', 'update', 'second', '--label', 'Independent', '--state-dir', f.state], f.env);
    assert.equal(changed.code, 0); assert.equal(changed.result.label, 'Independent');
  } finally { release(); await pending; }
  await noVendor(f);
});

// Account/read envelope: the second response in the 6 October recorded run,
// research/probe-scripts-2026-10-06/live/codex-all.json. The delayed response and
// temporary marker paths are synthetic variants for concurrent state changes.
async function delayedServer(f: Fixture): Promise<{ started: string; release: string }> {
  const program = join(f.tool, 'delayed.mjs'), started = join(f.tool, 'read-started'), release = join(f.tool, 'release-read');
  const script = `
    import { createInterface } from 'node:readline';
    import { existsSync, writeFileSync } from 'node:fs';
    const [started, release] = process.argv.slice(2);
    if (process.argv.includes('--version')) { console.log('codex-cli 0.159.2'); process.exit(0); }
    const send = (id, result) => console.log(JSON.stringify({ id, result }));
    for await (const line of createInterface({ input: process.stdin })) {
      const request = JSON.parse(line);
      if (!Object.hasOwn(request, 'id')) continue;
      if (request.method === 'initialize') send(request.id, { userAgent: 'synthetic test', codexHome: process.env.CODEX_HOME, platformFamily: 'unix', platformOs: 'macos' });
      else if (request.method === 'config/read') send(request.id, { config: { check_for_update_on_startup: false, web_search: 'live', cli_auth_credentials_store: 'file', analytics: { enabled: false }, features: { memories: false } } });
      else if (request.method === 'account/read') {
        writeFileSync(started, JSON.stringify({ ...request.params, toolPid: process.pid }));
        const timer = setInterval(() => { if (existsSync(release)) { clearInterval(timer); send(request.id, { account: { type: 'chatgpt', email: 'late@example.invalid', planType: 'pro' }, requiresOpenaiAuth: true }); } }, 5);
      } else if (request.method === 'account/logout' || request.method === 'account/login/cancel') send(request.id, {});
      else console.log(JSON.stringify({ id: request.id, error: { code: -32601, message: 'Unsupported synthetic method' } }));
    }
  `;
  await writeFile(program, script);
  await writeFile(join(f.tool, 'codex'), `#!/bin/sh\nexec ${quote(process.execPath)} ${quote(program)} ${quote(started)} ${quote(release)} "$@"\n`, { mode: 0o700 });
  return { started, release };
}

for (const mutation of ['sign-out', 'remove'] as const) {
  test(`subscriptions.late-check cannot resurrect an account after ${mutation}`, async t => {
    const f = await fixture(t);
    await create(f, 'work');
    const original = JSON.parse(await readFile(recordPath(f, 'work'), 'utf8'));
    await writeJson(recordPath(f, 'work'), { ...original, state: 'signed_in', account: { email: 'old@example.invalid' },
      checkedAt: '2026-10-06T00:00:00Z', lastUsage: { outcome: 'ok', fetchedAt: '2026-10-06T00:00:00Z', windows: [] } });
    const server = await delayedServer(f);
    const check = start(t, ['subscriptions', 'check', 'work', '--state-dir', f.state], f.env);
    await untilFile(server.started);
    const request = JSON.parse(await readFile(server.started, 'utf8'));
    t.after(() => {
      try { process.kill(-request.toolPid, 'SIGKILL'); } catch { try { process.kill(request.toolPid, 'SIGKILL'); } catch { /* Already gone. */ } }
    });
    assert.equal(request.refreshToken, true);
    const changed = await start(t, ['subscriptions', mutation, 'work', '--state-dir', f.state], f.env).done;
    assert.equal(changed.code, 0, changed.stdout);
    await writeFile(server.release, 'release');
    const late = await check.done;
    assert.equal(late.code, 1); assert.ok(['in_use', 'not_found'].includes(JSON.parse(late.stdout).error.code));
    const accounts = await invoke(['subscriptions', 'list', '--state-dir', f.state], f.env);
    assert.equal(accounts.code, 0);
    if (mutation === 'remove') {
      assert.equal(accounts.result.some((account: { id: string }) => account.id === 'work'), false);
      await assert.rejects(stat(recordPath(f, 'work')), { code: 'ENOENT' });
    } else {
      const work = accounts.result.find((account: { id: string }) => account.id === 'work');
      assert.equal(work.state, 'signed_out');
      for (const field of ['account', 'problem', 'lastUsage']) assert.equal(work[field], undefined);
      assert.deepEqual(work, JSON.parse(changed.stdout));
    }
  });
}

test('subscriptions.cancel-check stops a pending account request and its app-server', async t => {
  const f = await fixture(t);
  await create(f, 'work');
  const original = JSON.parse(await readFile(recordPath(f, 'work'), 'utf8'));
  await writeJson(recordPath(f, 'work'), { ...original, state: 'signed_in', checkedAt: '2026-10-06T00:00:00Z' });
  const server = await delayedServer(f);
  const pending = start(t, ['subscriptions', 'check', 'work', '--state-dir', f.state], f.env);
  await untilFile(server.started);
  const request = JSON.parse(await readFile(server.started, 'utf8'));
  t.after(() => {
    try { process.kill(-request.toolPid, 'SIGKILL'); } catch { try { process.kill(request.toolPid, 'SIGKILL'); } catch { /* Already gone. */ } }
  });
  pending.child.kill('SIGTERM');
  let deadline!: NodeJS.Timeout;
  try {
    const stopped = await Promise.race([pending.done, new Promise<never>((_resolve, reject) => {
      deadline = setTimeout(() => reject(new Error('Cancelling an account check must not wait for the vendor timeout.')), 3000);
    })]);
    assert.deepEqual(stopped, { code: 2, stdout: '', stderr: '' });
    assert.equal(await processOwner(request.toolPid), undefined);
    assert.equal(JSON.parse(await readFile(recordPath(f, 'work'), 'utf8')).state, 'signed_in');
  } finally { clearTimeout(deadline); }
});
