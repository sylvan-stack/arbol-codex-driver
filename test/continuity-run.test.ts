import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { TestContext } from 'node:test';
import { createHash } from 'node:crypto';
import { execFile, spawn } from 'node:child_process';
import { createInterface } from 'node:readline';
import { mkdir, readFile, readdir, rm, stat, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { promisify } from 'node:util';
import { cli, fixture, received } from './helpers.js';
import type { HistoryItem } from '../src/run-request.js';

const exec = promisify(execFile);
type Event = { type: string; seq: number; [key: string]: any };
const picture = { mediaType: 'image/png' as const, data: 'aQ==' };
const chatSessionId = 'opaque/../chat';
const hash = (value: string) => createHash('sha256').update(value).digest('hex');

async function ready(t: TestContext) {
  const f = await fixture(t);
  await writeFile(join(f.tool, 'scenario'), 'C14 success');
  await exec(process.execPath, [cli, 'subscriptions', 'sign-in', 'chatgpt', '--state-dir', f.state], { env: f.env, timeout: 10000 });
  await writeFile(join(f.tool, 'received.jsonl'), '');
  let index = 0;
  const mapPath = join(f.state, 'subscriptions', 'chatgpt', 'chats', hash(chatSessionId) + '.json');
  const request = async (fields: Record<string, unknown> = {}) => {
    const path = join(f.home, `request-${++index}.json`);
    await writeFile(path, JSON.stringify({ runId: `continuity-${index}`, chatSessionId, workingDirectory: f.home,
      tools: 'none', history: [], input: { role: 'user', text: 'hello' }, ...fields }));
    return path;
  };
  const run = async (fields: Record<string, unknown> = {}, part = 'plain', outcome = 'completed') => {
    await writeFile(join(f.tool, 'scenario'), 'C14 ' + part);
    const path = await request(fields);
    let result: { code?: number; stdout: string; stderr: string };
    try { result = await exec(process.execPath, [cli, 'run', '--request', path, '--state-dir', f.state], { env: f.env, timeout: 10000 }); }
    catch (error) { result = error as typeof result; }
    const events: Event[] = result.stdout.trim().split('\n').map(line => JSON.parse(line));
    assert.deepEqual(events.map(event => event.seq), events.map((_, index) => index + 1));
    assert.equal(events.filter(event => event.type === 'finished').length, 1); assert.equal(events.at(-1)!.outcome, outcome);
    assert.equal(result.code ?? 0, outcome === 'completed' ? 0 : 1, result.stderr);
    assert.equal(result.stderr, '');
    return events;
  };
  const map = async (): Promise<Record<string, any>> => JSON.parse(await readFile(mapPath, 'utf8'));
  const clear = async () => writeFile(join(f.tool, 'received.jsonl'), '');
  return { ...f, request, run, map, mapPath, clear };
}

function append(history: HistoryItem[], input: { text: string; images?: typeof picture[] }, events: Event[]): HistoryItem[] {
  return [...history, { type: 'message', role: 'user', ...input },
    ...events.filter(event => event.type === 'text' && !event.parentCallId).map(event => ({ type: 'message' as const, role: 'assistant' as const, text: event.text }))];
}
function started(events: Event[], continuity: string, reason?: string): void {
  const start = events.filter(event => event.type === 'started'); assert.equal(start.length, 1);
  assert.equal(start[0]!.continuity, continuity); assert.equal(start[0]!.rebuildReason, reason);
}
async function files(folder: string): Promise<string[]> {
  const result: string[] = [];
  for (const entry of await readdir(folder, { withFileTypes: true }).catch(() => [])) {
    const path = join(folder, entry.name);
    if (entry.isDirectory()) result.push(...await files(path)); else result.push(path);
  }
  return result;
}
function active(t: TestContext, args: string[], env: NodeJS.ProcessEnv) {
  const child = spawn(process.execPath, [cli, ...args], { env, stdio: 'pipe' });
  const events: Event[] = []; let stderr = '';
  const reader = createInterface({ input: child.stdout });
  reader.on('line', line => events.push(JSON.parse(line)));
  child.stderr.setEncoding('utf8'); child.stderr.on('data', text => { stderr += text; });
  const timeout = setTimeout(() => child.kill('SIGKILL'), 8000);
  const done = new Promise<{ code: number | null; stderr: string }>(resolve => child.once('close', code => { clearTimeout(timeout); resolve({ code, stderr }); }));
  t.after(() => { clearTimeout(timeout); if (child.exitCode === null && child.signalCode === null) child.kill('SIGKILL'); });
  const waitForStart = async () => {
    for (let n = 0; n < 200; n++) {
      if (events.some(event => event.type === 'started')) return;
      if (child.exitCode !== null || child.signalCode !== null) break;
      await new Promise(resolve => setTimeout(resolve, 10));
    }
    throw new Error(`Run did not start: ${JSON.stringify(events)} ${stderr}`);
  };
  return { child, events, done, waitForStart };
}

test('continuity.run resumes through the new process and applies every turn override without counting old usage', async t => {
  const f = await ready(t); const input = { text: 'secret-first', images: [picture] };
  const first = await f.run({ input: { role: 'user', ...input }, systemPrompt: 'same-system' }); started(first, 'fresh');
  const initial = await f.map(); assert.equal(initial.messages, 2); assert.equal(initial.chatSessionId, chatSessionId);
  assert.equal((await stat(f.mapPath)).mode & 0o777, 0o600);
  assert.deepEqual(await readdir(join(f.state, 'subscriptions', 'chatgpt', 'chats')), [hash(chatSessionId) + '.json']);
  await f.clear();
  const history = append([], input, first);
  const second = await f.run({ history, systemPrompt: 'same-system', model: 'gpt-6-astra', effort: 'high', serviceTier: 'priority', tools: 'all' });
  started(second, 'resumed'); assert.equal((await f.map()).conversation, initial.conversation);
  assert.equal(second.find(event => event.type === 'started')!.model, 'gpt-6-astra');
  assert.equal(second.at(-1)!.usage.model, 'gpt-6-astra');
  const records = await received(f.tool); const rpc = records.filter(record => record.stage === 'request').map(record => record.request.method);
  assert.equal(rpc.filter(method => method === 'thread/resume').length, 1);
  assert.equal(rpc.includes('thread/start'), false); assert.equal(rpc.includes('thread/inject_items'), false);
  assert.equal(records.filter(record => !record.stage && record.arguments[0] === 'app-server').length, 1);
  const turn = records.find(record => record.stage === 'input').request.params;
  assert.equal(turn.model, 'gpt-6-astra'); assert.equal(turn.effort, 'high'); assert.equal(turn.serviceTier, 'priority');
  assert.equal(turn.summary, 'detailed'); assert.equal(turn.approvalPolicy, 'never'); assert.deepEqual(turn.sandboxPolicy, { type: 'dangerFullAccess' });
  assert.equal(second.at(-1)!.usage.inputTokens, 3); assert.equal(second.at(-1)!.usage.outputTokens, 2);
  assert.equal((await readFile(f.mapPath, 'utf8')).includes(input.text), false);
  assert.deepEqual(await readdir(join(f.state, 'runs')), []); assert.deepEqual(await readdir(join(f.state, 'tmp')), []);
});

test('continuity.run ignores delayed restored usage arriving while accepting the resumed turn', async t => {
  const f = await ready(t); const first = await f.run(); const history = append([], { text: 'hello' }, first);
  const second = await f.run({ history }, 'delayed-usage'); started(second, 'resumed');
  const reports = second.filter(event => event.type === 'usage');
  assert.equal(reports.length, 1); assert.equal(reports[0]!.usage.inputTokens, 3); assert.equal(reports[0]!.usage.outputTokens, 2);
  assert.equal(second.at(-1)!.usage.inputTokens, 3); assert.equal(second.at(-1)!.usage.outputTokens, 2);
});

test('continuity.run fingerprints replies and images, ignores tool changes and reports checks in contract order', async t => {
  const f = await ready(t); const input = { text: 'first', images: [picture] };
  // Unknown input fields do not change its established user-message identity.
  const first = await f.run({ input: { role: 'user', ...input, type: 'tool_call' } });
  assert.equal((await f.map()).messages, 2);
  let history = append([], input, first);
  history = history.flatMap(item => item.type === 'message' && item.role === 'assistant' ?
    [{ ...item, text: item.text.slice(0, 2) }, { ...item, text: item.text.slice(2) }] : [item]);
  history.push({ type: 'tool_call', name: 'ignored-tool-change', input: {}, ok: true, result: 'ignored' });
  const split = await f.run({ history }); started(split, 'resumed'); history = append(history, { text: 'hello' }, split);
  const moved = join(f.home, 'moved'); await mkdir(moved);
  const changedReply = history.map((item, index) => index === history.length - 1 ? { ...item, text: 'replaced-answer' } : item);
  started(await f.run({ history: changedReply, workingDirectory: moved, systemPrompt: 'new' }), 'rebuilt', 'history_differs');
  const movedHistory = append(changedReply, { text: 'hello' }, []);
  // Use the exact committed history for the folder/prompt checks.
  const rebuiltHistory = [...movedHistory, { type: 'message' as const, role: 'assistant' as const, text: 'answer' }];
  started(await f.run({ history: rebuiltHistory, systemPrompt: 'another' }), 'rebuilt', 'working_folder_changed');
  const promptHistory = append(rebuiltHistory, { text: 'hello' }, [{ type: 'text', seq: 1, text: 'answer' }]);
  started(await f.run({ history: promptHistory, systemPrompt: 'changed-again' }), 'rebuilt', 'system_prompt_changed');
});

const nativeHistory: HistoryItem[] = [
  { type: 'message', role: 'user', text: 'earlier-picture', images: [picture] },
  { type: 'tool_call', name: 'shell', input: { command: 'printf history-shell-output', cwd: '/ignored' }, ok: false,
    result: { output: 'history-shell-output', exitCode: 2 }, error: 'history-error' },
  { type: 'tool_call', name: 'foreign_tool', input: { value: 'foreign-input' }, ok: true, result: { value: 'foreign-value' } },
  { type: 'message', role: 'assistant', text: 'earlier-answer' },
];

test('continuity.run rebuilds caller history in one native injection with paired synthetic tool identifiers', async t => {
  const f = await ready(t); const events = await f.run({ history: nativeHistory }); started(events, 'rebuilt', 'first_run');
  const records = await received(f.tool); const requests = records.filter(record => record.stage === 'request').map(record => record.request);
  const injections = requests.filter(request => request.method === 'thread/inject_items'); assert.equal(injections.length, 1);
  const items = injections[0].params.items;
  assert.deepEqual(items.map((item: any) => item.type), ['message', 'function_call', 'function_call_output', 'function_call', 'function_call_output', 'message']);
  assert.deepEqual(items[0].content, [{ type: 'input_text', text: 'earlier-picture' }, { type: 'input_image', image_url: 'data:image/png;base64,aQ==' }]);
  assert.equal(items[1].name, 'shell'); assert.deepEqual(JSON.parse(items[1].arguments), { command: 'printf history-shell-output', cwd: '/ignored' });
  assert.match(items[1].call_id, /^call_[a-zA-Z0-9]{24}$/); assert.equal(items[2].call_id, items[1].call_id);
  assert.equal(items[2].output, 'history-shell-output\nexit code: 2\nhistory-error');
  assert.equal(items[3].name, 'foreign_tool'); assert.notEqual(items[3].call_id, items[1].call_id); assert.equal(items[4].output, '{"value":"foreign-value"}');
  assert.equal(events.some(event => event.code === 'history_as_text'), false);
  const input = records.find(record => record.stage === 'input'); assert.equal(input.checks.nativeHistory, true); assert.equal(input.checks.labelledHistory, false);
  assert.deepEqual(input.checks.historyImages, [picture]);
});

test('continuity.run falls back visibly to labelled text and sends earlier pictures before the new pictures', async t => {
  const f = await ready(t);
  const events = await f.run({ history: nativeHistory, input: { role: 'user', text: 'current', images: [{ mediaType: 'image/webp', data: 'aGk=' }] } }, 'inject-refused');
  started(events, 'rebuilt', 'first_run'); assert.equal(events.filter(event => event.type === 'notice' && event.code === 'history_as_text').length, 1);
  const input = (await received(f.tool)).find(record => record.stage === 'input'); const text = input.request.params.input[0].text;
  assert.match(text, /^Earlier conversation, for context:/); assert.match(text, /\[User\]\nearlier-picture/);
  assert.match(text, /\[Tool call: shell\]/); assert.match(text, /\[Tool error\]\nhistory-shell-output\nexit code: 2\nhistory-error/);
  assert.match(text, /\[Tool result\]\n\{"value":"foreign-value"\}/); assert.match(text, /New message:\n\ncurrent$/);
  assert.deepEqual(input.checks.images.map((image: any) => image.data), ['aQ==', 'aGk=']);
  for (const image of input.checks.images) await assert.rejects(stat(image.path), { code: 'ENOENT' });
});

test('continuity.run treats vanished rollouts and native resume refusals as rebuilds', async t => {
  const f = await ready(t); const first = await f.run(); let history = append([], { text: 'hello' }, first);
  const initial = await f.map();
  for (const file of await files(join(f.state, 'subscriptions', 'chatgpt', 'home', 'sessions'))) if (file.endsWith('-' + initial.conversation + '.jsonl')) await rm(file);
  const gone = await f.run({ history }); started(gone, 'rebuilt', 'conversation_gone'); history = append(history, { text: 'hello' }, gone);
  const refused = await f.run({ history }, 'refuse'); started(refused, 'rebuilt', 'resume_refused');
  assert.equal(refused.filter(event => event.code === 'history_as_text').length, 1);
  assert.notEqual((await f.map()).conversation, initial.conversation);
});

test('continuity.run removes failed/cancelled resumed entries and never maps ephemeral or unnamed chats', async t => {
  const f = await ready(t); const first = await f.run(); const history = append([], { text: 'hello' }, first);
  const failed = await f.run({ history }, 'fail', 'failed'); started(failed, 'resumed'); await assert.rejects(stat(f.mapPath), { code: 'ENOENT' });
  const rebuilt = await f.run({ history }); started(rebuilt, 'rebuilt', 'first_run'); const next = append(history, { text: 'hello' }, rebuilt);
  const original = await readFile(f.mapPath, 'utf8');
  const oneOff = await f.run({ workingDirectory: undefined, history: next }); started(oneOff, 'rebuilt', 'no_chat_session');
  assert.equal(await readFile(f.mapPath, 'utf8'), original);
  const input = (await received(f.tool)).filter(record => record.stage === 'input').at(-1)!;
  assert.equal(input.checks.ephemeral, true); assert.equal(input.checks.savedPath, null);
  await f.run({ chatSessionId: undefined, history: next }); assert.equal(await readFile(f.mapPath, 'utf8'), original);
  await writeFile(join(f.tool, 'scenario'), 'C14 hold'); const path = await f.request({ history: next });
  const running = active(t, ['run', '--request', path, '--control', '--state-dir', f.state], f.env); await running.waitForStart();
  assert.equal(await readFile(f.mapPath, 'utf8'), original); running.child.stdin.write('{"type":"stop"}\n');
  assert.equal((await running.done).code, 2); assert.equal(running.events.at(-1)!.outcome, 'cancelled');
  await assert.rejects(stat(f.mapPath), { code: 'ENOENT' });
  assert.deepEqual(await readdir(join(f.state, 'tmp')), []);
});

test('continuity.run reserves resumes before peers and conditional failure cleanup preserves the peer entry', async t => {
  const f = await ready(t); const first = await f.run(); const history = append([], { text: 'hello' }, first);
  const initial = await f.map();
  await writeFile(join(f.tool, 'scenario'), 'C14 hold');
  const heldPath = await f.request({ history, input: { role: 'user', text: 'held' } });
  const held = active(t, ['run', '--request', heldPath, '--control', '--state-dir', f.state], f.env); await held.waitForStart();
  const peer = await f.run({ history, input: { role: 'user', text: 'peer' } }); started(peer, 'rebuilt', 'in_use');
  const peerEntry = await f.map(); assert.notEqual(peerEntry.conversation, initial.conversation);
  held.child.stdin.write('{"type":"stop"}\n'); assert.equal((await held.done).code, 2);
  assert.equal((await f.map()).conversation, peerEntry.conversation);
  const peerHistory = append(history, { text: 'peer' }, peer);
  started(await f.run({ history: peerHistory }), 'resumed');
});
