import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { TestContext } from 'node:test';
import { randomUUID } from 'node:crypto';
import { execFile } from 'node:child_process';
import { readFile, stat, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { Writable } from 'node:stream';
import { promisify } from 'node:util';
import { parseArguments } from '../src/arguments.js';
import { chatKey } from '../src/continuity.js';
import type { ChatEntry } from '../src/continuity.js';
import { EventStream } from '../src/event-stream.js';
import { run } from '../src/run.js';
import { State, writeJson } from '../src/state.js';
import { Subscriptions } from '../src/subscriptions.js';
import { cli, fixture } from './helpers.js';

const exec = promisify(execFile);

async function ready(t: TestContext) {
  const f = await fixture(t);
  await writeFile(join(f.tool, 'scenario'), 'C14 plain');
  await exec(process.execPath, [cli, 'subscriptions', 'sign-in', 'chatgpt', '--state-dir', f.state], { env: f.env, timeout: 10000 });
  const requestPath = join(f.home, 'request.json');
  const chatSessionId = 'output-failure-chat';
  const fields = { runId: 'initial', chatSessionId, workingDirectory: f.home, tools: 'none', history: [],
    input: { role: 'user', text: 'hello' } };
  await writeFile(requestPath, JSON.stringify(fields));
  await exec(process.execPath, [cli, 'run', '--request', requestPath, '--state-dir', f.state], { env: f.env, timeout: 10000 });
  const mapPath = join(f.state, 'subscriptions', 'chatgpt', 'chats', chatKey(chatSessionId) + '.json');
  const original = JSON.parse(await readFile(mapPath, 'utf8')) as ChatEntry;
  await writeFile(join(f.tool, 'scenario'), 'C14 refuse');
  await writeFile(requestPath, JSON.stringify({ ...fields, runId: 'output-failure', history: [
    { type: 'message', role: 'user', text: 'hello' }, { type: 'message', role: 'assistant', text: 'answer' },
  ] }));
  const state = new State(f.state); await state.initialize();
  const cancellation = new AbortController();
  const subscriptions = new Subscriptions(state, { toolPath: join(f.tool, 'codex') }, [],
    join(f.home, '.arbol', 'arbol-codex-driver.json'), f.env, cancellation.signal);
  const failedRun = async (type: 'started' | 'finished', beforeFailure: () => Promise<void> = async () => {}) => {
    const failure = new Error('Synthetic stdout write failure.');
    const events: Record<string, unknown>[] = [];
    const output = new Writable({ write(chunk: Buffer, _encoding, callback) {
      const event = JSON.parse(chunk.toString('utf8')) as Record<string, unknown>;
      events.push(event);
      if (event.type !== type) { callback(); return; }
      void beforeFailure().then(() => callback(failure), callback);
    } });
    // The write callback is the runner's error path; prevent the stream's own
    // error event from becoming an uncaught error in this direct-call fixture.
    output.on('error', () => {});
    await assert.rejects(run(parseArguments(['run', '--request', requestPath]), subscriptions,
      new EventStream(output), f.env, '0', cancellation.signal), error => error === failure);
    await assert.rejects(stat(join(f.state, 'runs', 'output-failure.json')), { code: 'ENOENT' });
    await assert.rejects(stat(join(f.state, 'tmp', 'output-failure')), { code: 'ENOENT' });
    return events;
  };
  return { ...f, state, mapPath, original, failedRun };
}

test('continuity.output removes the selected old map when a refused resume rebuild loses stdout at started', async t => {
  const f = await ready(t);
  const events = await f.failedRun('started');
  assert.equal(events[0]!.continuity, 'rebuilt'); assert.equal(events[0]!.rebuildReason, 'resume_refused');
  await assert.rejects(readFile(f.mapPath), { code: 'ENOENT' });
});

test('continuity.output preserves a newer completed map when a refused resume rebuild loses stdout', async t => {
  const f = await ready(t), newer = randomUUID();
  await f.failedRun('started', () => f.state.withSubscriptionLock('chatgpt', async () => {
    await writeJson(f.mapPath, { ...f.original, conversation: newer });
  }));
  assert.equal((JSON.parse(await readFile(f.mapPath, 'utf8')) as ChatEntry).conversation, newer);
});

test('continuity.output compensates a completed rebuilt map when the final event cannot be written', async t => {
  const f = await ready(t);
  let writtenConversation: string | undefined;
  const events = await f.failedRun('finished', async () => {
    writtenConversation = (JSON.parse(await readFile(f.mapPath, 'utf8')) as ChatEntry).conversation;
  });
  assert.equal(events.at(-1)!.outcome, 'completed');
  assert.ok(writtenConversation); assert.notEqual(writtenConversation, f.original.conversation);
  await assert.rejects(readFile(f.mapPath), { code: 'ENOENT' });
});
