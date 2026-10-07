import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { TestContext } from 'node:test';
import { mkdtemp, mkdir, readFile, realpath, rm, symlink, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { Failure } from '../src/errors.js';
import { readRunRequest } from '../src/run-request.js';
import type { RunRequest, RunRequestContext } from '../src/run-request.js';

const base = { history: [], tools: 'none', input: { role: 'user', text: 'message' } };
const invalid = (error: unknown): boolean => error instanceof Failure && error.result.code === 'invalid_input' && !error.result.retryable;
async function folder(t: TestContext): Promise<string> {
  const path = await mkdtemp(join(tmpdir(), 'syl86-request-'));
  t.after(async () => { await rm(path, { recursive: true, force: true }); });
  return path;
}

test('run.request merges CLI values over the request, preserves images and does not modify the source file', async t => {
  const home = await folder(t);
  const requestFile = join(home, 'request.json');
  const promptFile = join(home, 'prompt.txt');
  const previousDirectory = join(home, 'old');
  const newDirectory = join(home, 'new');
  await mkdir(previousDirectory); await mkdir(newDirectory);
  const image = { mediaType: 'image/png', data: 'aQ==' };
  const original = JSON.stringify({ ...base, runId: 'file-run', subscriptionId: 'file-subscription', model: 'file-model',
    effort: 'low', serviceTier: 'flex', systemPrompt: 'file instructions', workingDirectory: previousDirectory,
    additionalDirectories: [previousDirectory], labels: { exchange: 'file', source: 'file' },
    input: { ...base.input, images: [image] } });
  const prompt = 'Exact instructions\nwith "quotes" and a final newline.\n';
  await writeFile(requestFile, original); await writeFile(promptFile, prompt);
  const request = await readRunRequest({ request: requestFile, subscription: 'work', model: 'gpt-5.4', effort: 'high',
    'service-tier': 'fast', 'run-id': 'cli-run', 'chat-session': 'opaque chat / id', 'system-prompt-file': promptFile,
    cwd: newDirectory, 'add-dir': [newDirectory], label: ['exchange=cli', 'empty=', 'equals=a=b'], control: true, output: 'text' },
  { message: 'new message' });
  assert.equal(request.runId, 'cli-run'); assert.equal(request.subscriptionId, 'work');
  assert.equal(request.model, 'gpt-5.4'); assert.equal(request.effort, 'high'); assert.equal(request.serviceTier, 'fast');
  assert.equal(request.systemPrompt, prompt); assert.equal(request.workingDirectory, await realpath(newDirectory));
  assert.deepEqual(request.additionalDirectories, [newDirectory]);
  assert.deepEqual(request.input, { role: 'user', text: 'new message', images: [image] });
  assert.deepEqual(request.labels, { exchange: 'cli', source: 'file', empty: '', equals: 'a=b' });
  assert.equal(request.chatSessionId, 'opaque chat / id'); assert.equal(request.control, true); assert.equal(request.output, 'text');
  assert.equal(await readFile(requestFile, 'utf8'), original);
});

test('run.request selects Subscription settings and retains the vendor defaults when none are configured', async () => {
  const minimal = await readRunRequest({}, { message: 'hello' });
  assert.match(minimal.runId, /^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$/);
  assert.equal(minimal.subscriptionId, 'chatgpt'); assert.equal(minimal.model, undefined); assert.equal(minimal.effort, undefined);
  assert.equal(minimal.tools, 'none'); assert.deepEqual(minimal.history, []); assert.deepEqual(minimal.searchPath, []);
  assert.equal(minimal.control, false); assert.equal(minimal.output, 'events');
  const settings = { defaultSubscription: 'configured', subscriptions: {
    configured: { defaultModel: 'gpt-configured', defaultEffort: 'medium' },
    work: { defaultModel: 'gpt-work', defaultEffort: 'high' },
  } };
  const configured = await readRunRequest({}, { settings, message: 'hello' });
  assert.equal(configured.subscriptionId, 'configured'); assert.equal(configured.model, 'gpt-configured'); assert.equal(configured.effort, 'medium');
  assert.equal(configured.effortFromSettings, true);
  const selected = await readRunRequest({ subscription: 'work', model: 'explicit' }, { settings, message: 'hello' });
  assert.equal(selected.subscriptionId, 'work'); assert.equal(selected.model, 'explicit'); assert.equal(selected.effort, 'high');
  assert.equal(selected.effortFromSettings, true);
  const explicitEffort = await readRunRequest({ effort: 'high' }, { settings, message: 'hello' });
  assert.equal(explicitEffort.effortFromSettings, false); assert.equal(minimal.effortFromSettings, false);
});

test('run.request reads one stdin request line, retains history and accepts supported image formats', async () => {
  let reads = 0;
  const images = ['image/png', 'image/jpeg', 'image/webp', 'image/gif'].map(mediaType => ({ mediaType, data: 'aQ==' }));
  const history = [ { type: 'message', role: 'user', text: 'earlier', images },
    { type: 'tool_call', name: 'shell', input: { command: 'pwd', cwd: '/repository' }, ok: true, result: { output: '/repository', exitCode: 0 } },
    { type: 'tool_call', name: 'other-driver-tool', input: ['opaque'], ok: false, result: null, error: 'failed' },
    { type: 'message', role: 'assistant', text: 'reply' } ];
  const request = await readRunRequest({ request: '-', control: true }, {
    firstLine: async () => { reads++; return JSON.stringify({ ...base, history, input: { ...base.input, images },
      searchPath: ['/extra/bin'], limits: { idleSeconds: 0, totalSeconds: 0.25 } }); },
  });
  assert.equal(reads, 1); assert.deepEqual(request.history, history); assert.deepEqual(request.input.images, images);
  assert.deepEqual(request.searchPath, ['/extra/bin']); assert.deepEqual(request.limits, { idleSeconds: 0, totalSeconds: 0.25 });
  assert.equal(request.control, true);
});

test('run.request keeps valid caller identity on a request refusal and labels are opaque string keys', async t => {
  const home = await folder(t);
  const labels = JSON.parse('{"exchange":"42","__proto__":"opaque","constructor":"label"}');
  let identity: { runId: string; labels: RunRequest['labels'] } | undefined;
  await assert.rejects(readRunRequest({ request: '-', label: ['__proto__=cli'] }, {
    firstLine: async () => JSON.stringify({ ...base, runId: 'refused', labels, workingDirectory: join(home, 'missing') }),
    identity: (runId, labels) => { identity = { runId, labels }; },
  }), invalid);
  assert.equal(identity?.runId, 'refused');
  assert.deepEqual(identity?.labels, JSON.parse('{"exchange":"42","__proto__":"cli","constructor":"label"}'));
});

test('run.request validates folders before a tool can be started and resolves a working-folder symlink', async t => {
  const home = await folder(t);
  const work = join(home, 'work'); const link = join(home, 'link'); const file = join(home, 'file');
  await mkdir(work); await symlink(work, link); await writeFile(file, 'ordinary file');
  const request = await readRunRequest({ tools: 'all', cwd: link, 'add-dir': work }, { message: 'hello' });
  assert.equal(request.workingDirectory, await realpath(work));
  for (const options of [{ tools: 'all' }, { cwd: 'relative' }, { cwd: join(home, 'missing') }, { cwd: file },
    { 'add-dir': ['relative'] }, { 'add-dir': [join(home, 'missing')] }, { 'add-dir': [file] }]) {
    await assert.rejects(readRunRequest(options, { message: 'hello' }), invalid);
  }
});

test('run.request rejects malformed envelopes, settings, labels, history, images and limits', async () => {
  const malformed = [ null, [], {}, { ...base, runId: '../unsafe' }, { ...base, runId: 'a'.repeat(129) },
    { ...base, model: '' }, { ...base, effort: 1 }, { ...base, subscriptionId: false }, { ...base, serviceTier: null },
    { ...base, systemPrompt: [] }, { ...base, chatSessionId: '' }, { ...base, labels: { label: 1 } },
    { ...base, labels: [] }, { ...base, tools: 'some' }, { ...base, history: {} },
    { ...base, history: [null] }, { ...base, history: [{ type: 'message', role: 'system', text: 'bad' }] },
    { ...base, history: [{ type: 'message', role: 'user', text: 1 }] },
    { ...base, history: [{ type: 'tool_call', name: 'tool', ok: true }] },
    { ...base, history: [{ type: 'tool_call', name: '', input: {}, ok: true }] },
    { ...base, history: [{ type: 'tool_call', name: 'shell', input: {}, ok: true }] },
    { ...base, history: [{ type: 'tool_call', name: 'tool', input: {}, ok: 'yes' }] },
    { ...base, history: [{ type: 'tool_call', name: 'tool', input: {}, ok: false, error: {} }] },
    { ...base, history: [{ type: 'unknown' }] }, { ...base, input: { role: 'assistant', text: 'bad' } },
    { ...base, input: { role: 'user', text: null } }, { ...base, searchPath: ['relative'] },
    { ...base, additionalDirectories: '/folder' }, { ...base, limits: [] }, { ...base, limits: { startSeconds: 1 } },
    { ...base, limits: { idleSeconds: -1 } }, { ...base, limits: { totalSeconds: '1' } },
  ];
  for (const value of malformed) {
    await assert.rejects(readRunRequest({ request: '-' }, { firstLine: async () => JSON.stringify(value) }), invalid);
  }
  for (const image of [{ mediaType: 'application/pdf', data: 'aQ==' }, { mediaType: 'image/png', data: '' },
    { mediaType: 'image/png', data: 'aQ' }, { mediaType: 'image/png', data: 'a===' },
    { mediaType: 'image/png', data: 'a Q=' }, { mediaType: 'image/png', data: 12 }]) {
    for (const value of [{ ...base, input: { ...base.input, images: [image] } },
      { ...base, history: [{ type: 'message', role: 'user', text: 'earlier', images: [image] }] }]) {
      await assert.rejects(readRunRequest({ request: '-' }, { firstLine: async () => JSON.stringify(value) }), invalid);
    }
  }
  await assert.rejects(readRunRequest({ request: '-' }, { firstLine: async () => '{"history":[],"tools":"none","input":{"role":"user","text":"hello"},"limits":{"totalSeconds":1e999}}' }), invalid);
});

test('run.request refuses unreadable files, invalid JSON and invalid CLI values without exposing their contents', async t => {
  const home = await folder(t); const badFile = join(home, 'invalid.json'); const sentinel = 'synthetic-private-request-sentinel';
  await writeFile(badFile, sentinel);
  const cases: [Record<string, string | boolean | string[]>, RunRequestContext][] = [
    [{ request: badFile }, {}], [{ request: join(home, 'missing') }, {}],
    [{ request: '-' }, {}], [{ 'system-prompt-file': join(home, 'missing') }, { message: 'hello' }],
    [{ label: ['missing-equals'] }, { message: 'hello' }], [{ label: ['=missing-key'] }, { message: 'hello' }],
    [{ model: true }, { message: 'hello' }], [{ control: 'true' }, { message: 'hello' }],
    [{ output: 'unknown' }, { message: 'hello' }],
  ];
  for (const [options, context] of cases) {
    await assert.rejects(readRunRequest(options, context), (error: unknown) => {
      assert.ok(invalid(error)); assert.equal(JSON.stringify((error as Failure).result).includes(sentinel), false); return true;
    });
  }
});

test('run.request accepts request-file messages larger than a vendor event line', async () => {
  const text = 'x'.repeat(4 * 1024 * 1024 + 1);
  const request = await readRunRequest({ request: '-' }, { firstLine: async () => JSON.stringify({ ...base, input: { role: 'user', text } }) });
  assert.equal(request.input.text, text);
});
