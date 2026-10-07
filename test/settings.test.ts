import { test } from 'node:test';
import type { TestContext } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { readSettings, settingsPath, isObject } from '../src/settings.js';
import { Failure } from '../src/errors.js';

async function temporary(t: TestContext): Promise<string> {
  const directory = await mkdtemp(join(tmpdir(), 'arbol-codex-settings-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  return directory;
}
const plain = (value: unknown): unknown => JSON.parse(JSON.stringify(value));

test('settings uses the Codex component path and defaults when its file is missing', async t => {
  const home = await temporary(t);
  assert.equal(settingsPath(home), join(home, '.arbol', 'arbol-codex-driver.json'));
  assert.deepEqual(await readSettings(settingsPath(home)), { settings: {}, notices: [] });
  assert.equal(isObject({}), true);
  for (const value of [null, [], '', 0, true]) assert.equal(isObject(value), false);
});

test('settings reloads edited defaults without writing the settings file', async t => {
  const home = await temporary(t), file = settingsPath(home);
  await mkdir(join(home, '.arbol'));
  const first = JSON.stringify({ defaultSubscription: 'first', subscriptions: { first: { defaultModel: 'model-one', defaultEffort: 'high' } } });
  await writeFile(file, first);
  assert.deepEqual(plain((await readSettings(file)).settings), JSON.parse(first));
  assert.equal(await readFile(file, 'utf8'), first);
  const second = JSON.stringify({ toolPath: '/custom/codex', defaultSubscription: 'second', subscriptions: { second: { defaultModel: 'model-two' } } });
  await writeFile(file, second);
  assert.deepEqual(plain((await readSettings(file)).settings), JSON.parse(second));
  assert.equal(await readFile(file, 'utf8'), second);
});

test('settings validates every known shape and names faulty fields without their values', async t => {
  const home = await temporary(t), file = join(home, 'settings.json'), sentinel = 'synthetic-secret-sentinel';
  const invalid: [unknown, string][] = [
    [null, '(root)'], [[], '(root)'], [sentinel, '(root)'],
    [{ toolPath: 4 }, 'toolPath'], [{ defaultSubscription: [] }, 'defaultSubscription'], [{ defaultSubscription: '' }, 'defaultSubscription'],
    [{ subscriptions: [] }, 'subscriptions'], [{ subscriptions: { work: null } }, 'subscriptions.work'],
    [{ subscriptions: { work: { defaultModel: [] } } }, 'subscriptions.work.defaultModel'],
    [{ subscriptions: { work: { defaultEffort: false } } }, 'subscriptions.work.defaultEffort'],
    [{ subscriptions: { work: { settings: [] } } }, 'subscriptions.work.settings'],
    [{ subscriptions: { work: { secret: sentinel } } }, 'subscriptions.work.secret'],
    [{ subscriptions: { work: { secret: { from: sentinel } } } }, 'subscriptions.work.secret.from'],
    [{ subscriptions: { work: { secret: { from: 'command', command: [] } } } }, 'subscriptions.work.secret.command'],
    [{ subscriptions: { work: { secret: { from: 'command', command: ['', sentinel] } } } }, 'subscriptions.work.secret.command'],
    [{ subscriptions: { work: { secret: { from: 'command', command: ['program', 123, sentinel] } } } }, 'subscriptions.work.secret.command'],
  ];
  for (const [value, field] of invalid) {
    const contents = JSON.stringify(value);
    await writeFile(file, contents);
    await assert.rejects(readSettings(file), (error: unknown) => {
      assert.ok(error instanceof Failure);
      assert.equal(error.result.code, 'invalid_input');
      assert.ok(error.message.includes(file));
      assert.ok(error.message.includes(field));
      assert.equal(error.message.includes(sentinel), false);
      return true;
    });
    assert.equal(await readFile(file, 'utf8'), contents);
  }
});

test('settings refuses malformed and unreadable files without leaking contents or underlying diagnostics', async t => {
  const home = await temporary(t), file = join(home, 'settings.json'), sentinel = 'synthetic-secret-sentinel';
  await writeFile(file, 'malformed ' + sentinel);
  await assert.rejects(readSettings(file), (error: unknown) => {
    assert.ok(error instanceof Failure);
    assert.equal(error.result.code, 'invalid_input');
    assert.equal(error.message, `Settings file ${file} is not valid JSON.`);
    assert.equal(JSON.stringify(error.result).includes(sentinel), false);
    return true;
  });
  const directory = join(home, 'unreadable');
  await mkdir(directory);
  await assert.rejects(readSettings(directory), (error: unknown) => {
    assert.ok(error instanceof Failure);
    assert.equal(error.result.code, 'invalid_input');
    assert.equal(error.message, `Cannot read settings file ${directory}.`);
    return true;
  });
});

test('settings drops unknown keys with notices, and accepts only secret-source references', async t => {
  const home = await temporary(t), file = join(home, 'settings.json'), sentinel = 'synthetic-secret-sentinel';
  const input = { future: sentinel, subscriptions: {
    work: { defaultModel: 'model-one', future: sentinel, settings: { futureFamilySetting: true }, secret: { from: 'command', command: ['pass', 'show', 'work'], future: sentinel } },
    personal: { secret: { from: 'keychain', command: [sentinel] } },
  } };
  await writeFile(file, JSON.stringify(input));
  const { settings, notices } = await readSettings(file);
  assert.deepEqual(plain(settings), { subscriptions: {
    work: { defaultModel: 'model-one', settings: { futureFamilySetting: true }, secret: { from: 'command', command: ['pass', 'show', 'work'] } },
    personal: { secret: { from: 'keychain' } },
  } });
  assert.equal(notices.length, 4);
  for (const notice of notices) {
    assert.equal(notice.code, 'unknown_setting');
    assert.ok(notice.message.includes(file));
    assert.equal(notice.message.includes(sentinel), false);
  }
  for (const name of ['future', 'subscriptions.work.future', 'subscriptions.work.secret.future', 'subscriptions.personal.secret.command']) {
    assert.ok(notices.some(notice => notice.message.includes(`setting ${name} in`)), name);
  }
  assert.equal(JSON.stringify(settings).includes(sentinel), false);
});

test('settings keeps identifiers safe from object prototype collisions', async t => {
  const home = await temporary(t), file = join(home, 'settings.json');
  await writeFile(file, '{"subscriptions":{"__proto__":{"defaultModel":"model-one"},"constructor":{"defaultEffort":"high"}}}');
  const { settings } = await readSettings(file);
  assert.equal(Object.getPrototypeOf(settings.subscriptions), null);
  assert.equal(settings.subscriptions!.__proto__!.defaultModel, 'model-one');
  assert.deepEqual(settings.subscriptions!['constructor'], { defaultEffort: 'high' });
});
