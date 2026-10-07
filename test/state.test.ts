import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { access, chmod, mkdir, mkdtemp, readFile, readdir, rm, stat, utimes, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import type { TestContext } from 'node:test';
import { pathToFileURL } from 'node:url';
import { promisify } from 'node:util';
import { DriverFailure } from '../src/errors.js';
import { State, atomicWrite, defaultStateDirectory, fixedWait, ownerAlive, parseOwner, prepareFile, processOwner, readJson, writeJson } from '../src/state.js';

const exec = promisify(execFile);
const moduleUrl = pathToFileURL(join(import.meta.dirname, '../src/state.js')).href;
const dead = { owner: { pid: 2147483647, startedAt: '2000-01-01T00:00:00Z' } };
async function fixture(t: TestContext): Promise<string> {
  const path = await mkdtemp(join(tmpdir(), 'syl79-state-'));
  t.after(async () => { await rm(path, { recursive: true, force: true }); });
  return path;
}
const worker = `
  import { readFile } from 'node:fs/promises';
  import { join } from 'node:path';
  import { State, writeJson } from ${JSON.stringify(moduleUrl)};
  const [directory, id, count] = process.argv.slice(1);
  const state = new State(directory);
  await state.initialize();
  for (let i = 0; i < Number(count); i++) {
    await state.withSubscriptionLock(id, async () => {
      const path = join(state.subscription(id), 'record.json');
      let record = { count: 0 };
      try { record = JSON.parse(await readFile(path, 'utf8')); }
      catch (error) { if (error.code !== 'ENOENT') throw error; }
      await new Promise(resolve => setTimeout(resolve, 3));
      await writeJson(path, { count: record.count + 1 });
    });
  }
`;
async function compete(directory: string, id: string, count: number): Promise<void> {
  await Promise.all(Array.from({ length: 4 }, () => exec(process.execPath,
    ['--input-type=module', '-e', worker, directory, id, String(count)], {
      env: { PATH: '/usr/bin:/bin', LC_ALL: 'C', TZ: 'UTC' }, timeout: 15000,
    })));
}

test('state.layout initializes empty state lazily and keeps its own files private', async t => {
  const parent = await fixture(t);
  const directory = join(parent, 'empty');
  const state = new State(directory);
  await state.initialize();
  assert.equal(defaultStateDirectory('/home/example'), '/home/example/Library/Application Support/Arbol/drivers/codex');
  assert.equal(await readFile(join(directory, 'format'), 'utf8'), '1\n');
  assert.deepEqual(await readdir(directory), ['format']);
  assert.equal((await stat(directory)).mode & 0o777, 0o700);
  assert.equal((await stat(join(directory, 'format'))).mode & 0o777, 0o600);
  assert.equal(await readJson(join(state.subscription('openai'), 'record.json')), undefined);
  await chmod(directory, 0o755);
  await chmod(join(directory, 'format'), 0o644);
  await state.initialize();
  assert.equal((await stat(directory)).mode & 0o777, 0o700);
  assert.equal((await stat(join(directory, 'format'))).mode & 0o777, 0o600);
  for (const id of ['', '../outside', '.', '..', 'a/b', 'a\\b', 'x'.repeat(129)]) {
    assert.throws(() => state.subscription(id), DriverFailure);
  }
});

test('state.format refuses newer or malformed formats before changing any files or permissions', async t => {
  const directory = await fixture(t);
  const state = new State(directory);
  const path = join(directory, 'format');
  await writeFile(join(directory, 'sentinel'), 'untouched', { mode: 0o644 });
  for (const format of ['2\n', '9999999999999999999999999999999999999999\n', 'secret malformed state', '', '0\n', '1.0\n', '-1\n']) {
    await writeFile(path, format, { mode: 0o644 });
    await chmod(directory, 0o755);
    const before = await stat(path);
    await assert.rejects(state.initialize(), (error: unknown) => {
      assert.ok(error instanceof DriverFailure);
      assert.equal(error.result.code, /^\d+\n$/.test(format) && BigInt(format.trim()) > 1n ? 'state_newer' : 'internal');
      assert.ok(!error.message.includes('secret malformed state'));
      if (error.result.code === 'state_newer') {
        assert.ok(error.message.includes(format.trim()));
        assert.ok(error.message.includes('supported format 1'));
      }
      return true;
    });
    assert.equal(await readFile(path, 'utf8'), format);
    assert.equal((await stat(path)).ino, before.ino);
    assert.equal((await stat(path)).mode & 0o777, 0o644);
    assert.equal((await stat(directory)).mode & 0o777, 0o755);
    assert.deepEqual((await readdir(directory)).sort(), ['format', 'sentinel']);
    assert.equal(await readFile(join(directory, 'sentinel'), 'utf8'), 'untouched');
  }
});

test('state.atomic-write readers see complete versions and failed replacement cleans its scratch file', async t => {
  const directory = await fixture(t);
  const path = join(directory, 'record.json');
  const a = JSON.stringify({ count: 1, data: 'a'.repeat(20000) });
  const b = JSON.stringify({ count: 2, data: 'b'.repeat(20000) });
  await atomicWrite(path, a);
  let reading = true;
  const reader = (async () => {
    while (reading) {
      const text = await readFile(path, 'utf8');
      assert.ok(text === a || text === b);
    }
  })();
  try { for (let i = 0; i < 20; i++) await atomicWrite(path, i % 2 ? a : b); }
  finally { reading = false; await reader; }
  assert.equal((await stat(path)).mode & 0o777, 0o600);
  assert.deepEqual(await readdir(directory), ['record.json']);
  const targetDirectory = join(directory, 'directory');
  await mkdir(targetDirectory);
  await assert.rejects(atomicWrite(targetDirectory, 'cannot rename over a directory'));
  assert.deepEqual((await readdir(directory)).sort(), ['directory', 'record.json']);
  const temporary = await prepareFile(path, 'complete temporary record');
  assert.equal(join(directory, temporary.split('/').at(-1)!), temporary);
  assert.equal(await readFile(temporary, 'utf8'), 'complete temporary record');
  assert.equal((await stat(temporary)).mode & 0o777, 0o600);
});

test('state.read-json treats absence as empty and reports malformed records without their contents', async t => {
  const directory = await fixture(t);
  const path = join(directory, 'record.json');
  assert.equal(await readJson(path), undefined);
  await writeJson(path, { value: 'π' });
  assert.deepEqual(await readJson(path), { value: 'π' });
  await writeFile(path, 'a-secret-in-an-unfinished-json-file');
  await assert.rejects(readJson(path), (error: unknown) =>
    error instanceof DriverFailure && error.result.code === 'internal' && !error.message.includes('a-secret'));
});

test('state.owner checks PID and process start within two seconds using ps in a clean C environment', async () => {
  const owner = await processOwner(process.pid);
  assert.ok(owner);
  assert.equal(await ownerAlive(owner), true);
  for (const offset of [-2000, 2000]) {
    assert.equal(await ownerAlive({ ...owner, startedAt: new Date(Date.parse(owner.startedAt) + offset).toISOString() }), true);
  }
  assert.equal(await ownerAlive({ ...owner, startedAt: new Date(Date.parse(owner.startedAt) + 3000).toISOString() }), false);
  assert.equal(await ownerAlive({ pid: 2147483647, startedAt: owner.startedAt }), false);
  for (const value of [undefined, [], {}, { pid: 0, startedAt: owner.startedAt }, { pid: 1.5, startedAt: owner.startedAt }, { pid: 1, startedAt: 'secret-invalid-time' }]) {
    assert.throws(() => parseOwner(value), (error: unknown) => error instanceof DriverFailure && !error.message.includes('secret'));
  }
  const { stdout } = await exec(process.execPath, ['--input-type=module', '-e', `
    import { processOwner } from ${JSON.stringify(moduleUrl)};
    console.log(JSON.stringify(await processOwner(process.pid)));
  `], { env: { PATH: '/not/a/path', LC_ALL: 'invalid-locale', TZ: 'Pacific/Honolulu', PS_FORMAT: 'args' }, timeout: 5000 });
  const child = parseOwner(JSON.parse(stdout));
  assert.ok(Math.abs(Date.now() - Date.parse(child.startedAt)) < 5000);
});

test('state.lock serializes competing processes without losing changes', async t => {
  const directory = await fixture(t);
  const state = new State(directory);
  await state.initialize();
  await compete(directory, 'openai', 8);
  assert.deepEqual(await readJson(join(state.subscription('openai'), 'record.json')), { count: 32 });
  assert.deepEqual(await readdir(state.subscription('openai')), ['record.json']);
  assert.equal((await stat(join(directory, 'subscriptions'))).mode & 0o777, 0o700);
  assert.equal((await stat(state.subscription('openai'))).mode & 0o777, 0o700);
});

test('state.lock takes over dead owners and rejects a reused PID as the old owner', async t => {
  const directory = await fixture(t);
  const state = new State(directory);
  await state.initialize();
  const subscription = state.subscription('openai');
  for (const pid of [2147483647, process.pid]) {
    await writeJson(join(subscription, 'lock'), { owner: { pid, startedAt: '2000-01-01T00:00:00Z' } });
    await state.withSubscriptionLock('openai', async () => { await writeJson(join(subscription, 'record.json'), { pid }); });
    await assert.rejects(access(join(subscription, 'lock')));
  }
  await writeJson(join(subscription, 'record.json'), { count: 0 });
  await writeJson(join(subscription, 'lock'), dead);
  await compete(directory, 'openai', 4);
  assert.deepEqual(await readJson(join(subscription, 'record.json')), { count: 16 });
});

test('state.lock simultaneous calls recover even when earlier stale-lock reapers were killed', async t => {
  const directory = await fixture(t);
  const state = new State(directory);
  await state.initialize();
  const subscription = state.subscription('openai');
  await writeJson(join(subscription, 'lock'), dead);
  const lockInode = (await stat(join(subscription, 'lock'))).ino;
  const reaper = join(subscription, `.write-reap-${lockInode}`);
  await writeJson(reaper, dead);
  const reaperInode = (await stat(reaper)).ino;
  await writeJson(join(subscription, `.write-reap-${reaperInode}`), dead);
  await compete(directory, 'openai', 4);
  assert.deepEqual(await readJson(join(subscription, 'record.json')), { count: 16 });
  assert.deepEqual(await readdir(subscription), ['record.json']);
});

test('state.lock timeout names the live owner while other Subscriptions remain independent', async t => {
  const directory = await fixture(t);
  const state = new State(directory);
  await state.initialize();
  const subscription = state.subscription('openai');
  const owner = await processOwner(process.pid);
  assert.ok(owner);
  await writeJson(join(subscription, 'lock'), { owner });
  const started = performance.now();
  const blocked = assert.rejects(state.withSubscriptionLock('openai', async () => {
    assert.fail('a live lock cannot be taken');
  }, { ARBOL_TEST_TIME_SCALE: '20' }), (error: unknown) =>
    error instanceof DriverFailure && error.result.code === 'internal' && error.message.includes(String(process.pid)) && error.message.includes(owner.startedAt));
  await state.withSubscriptionLock('another', async () => { await writeJson(join(state.subscription('another'), 'record.json'), { ready: true }); });
  assert.deepEqual(await readJson(join(state.subscription('another'), 'record.json')), { ready: true });
  await blocked;
  assert.ok(performance.now() - started >= 500);
  assert.ok(performance.now() - started < 3000);
  assert.deepEqual(await readdir(subscription), ['lock']);
});

test('state.lock failures release owned locks and refuse malformed lock owners safely', async t => {
  const directory = await fixture(t);
  const state = new State(directory);
  await state.initialize();
  const subscription = state.subscription('openai');
  await assert.rejects(state.withSubscriptionLock('openai', async () => { throw new Error('change failed'); }), /change failed/);
  assert.deepEqual(await readdir(subscription), []);
  await state.withSubscriptionLock('openai', async () => {});
  assert.deepEqual(await readdir(subscription), []);
  for (const contents of ['secret unfinished lock', JSON.stringify({ owner: { pid: 'secret' } })]) {
    await writeFile(join(subscription, 'lock'), contents);
    await assert.rejects(state.withSubscriptionLock('openai', async () => {}), (error: unknown) =>
      error instanceof DriverFailure && error.result.code === 'internal' && !error.message.includes('secret'));
    assert.equal(await readFile(join(subscription, 'lock'), 'utf8'), contents);
    assert.deepEqual(await readdir(subscription), ['lock']);
  }
});

test('state.unfinished-writes removes only old driver writes and leaves vendor homes and run scratch alone', async t => {
  const directory = await fixture(t);
  const state = new State(directory);
  await state.initialize();
  const paths = ['.write-root', 'runs/.write-run', 'subscriptions/openai/.write-record', 'subscriptions/openai/chats/.write-chat', 'subscriptions/openai/home/.write-vendor', 'tmp/run/.write-scratch'];
  for (const name of paths) {
    const path = join(directory, name);
    await writeJson(path, { value: name });
    await utimes(path, new Date(Date.now() - 120000), new Date(Date.now() - 120000));
  }
  const fresh = join(directory, '.write-fresh');
  await writeJson(fresh, { current: true });
  await state.clearUnfinishedWrites();
  for (const name of paths.slice(0, 4)) assert.equal(await readJson(join(directory, name)), undefined);
  for (const name of paths.slice(4)) assert.deepEqual(await readJson(join(directory, name)), { value: name });
  assert.deepEqual(await readJson(fresh), { current: true });
});

test('state.time-scale divides fixed waits and rejects invalid values', () => {
  assert.equal(fixedWait(10000, {}), 10000);
  assert.equal(fixedWait(10000, { ARBOL_TEST_TIME_SCALE: '20' }), 500);
  assert.equal(fixedWait(50, { ARBOL_TEST_TIME_SCALE: '10' }), 5);
  for (const value of ['0', '-1', 'no', 'Infinity', '']) {
    assert.throws(() => fixedWait(1, { ARBOL_TEST_TIME_SCALE: value }), DriverFailure);
  }
});
