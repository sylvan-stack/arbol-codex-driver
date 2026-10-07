import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { TestContext } from 'node:test';
import { execFile, spawn } from 'node:child_process';
import { promisify } from 'node:util';
import { createInterface } from 'node:readline';
import { mkdir, readFile, realpath, stat, unlink, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { fixture, cli, received } from './helpers.js';
import type { ProcessEnv } from '../src/types.js';
import { ownerAlive } from '../src/state.js';
const exec = promisify(execFile);
type Event = { type: string; runId: string; seq: number; [key: string]: any };

async function ready(t: TestContext, scenario = 'C10 success') {
  const f = await fixture(t);
  await writeFile(join(f.tool, 'scenario'), 'C10 success');
  await exec(process.execPath, [cli, 'subscriptions', 'sign-in', 'chatgpt', '--state-dir', f.state], { env: f.env, timeout: 10000 });
  await writeFile(join(f.tool, 'scenario'), scenario);
  await writeFile(join(f.tool, 'received.jsonl'), '');
  return f;
}
async function run(args: string[], env: ProcessEnv): Promise<{ code: number; events: Event[]; stdout: string; stderr: string }> {
  let result: { stdout: string; stderr: string; code?: number };
  try { result = await exec(process.execPath, [cli, ...args], { env, timeout: 10000 }); }
  catch (error) { result = error as typeof result; }
  return { code: result.code ?? 0, ...result,
    events: result.stdout.trim() ? result.stdout.trim().split('\n').map(line => JSON.parse(line)) : [] };
}
function ordered(events: Event[], outcome: string): Event {
  assert.deepEqual(events.map(event => event.seq), events.map((_, index) => index + 1));
  assert.equal(events.filter(event => event.type === 'finished').length, 1);
  assert.equal(events.at(-1)?.type, 'finished'); assert.equal(events.at(-1)?.outcome, outcome);
  assert.ok(events.every(event => event.runId === events[0]!.runId));
  return events.at(-1)!;
}
async function cleaned(state: string, runId: string): Promise<void> {
  for (const path of [join(state, 'runs', runId + '.json'), join(state, 'tmp', runId)]) {
    await assert.rejects(stat(path), (error: any) => error.code === 'ENOENT');
  }
}
function active(t: TestContext, args: string[], env: ProcessEnv) {
  const child = spawn(process.execPath, [cli, ...args], { env, stdio: 'pipe' });
  const deadline = setTimeout(() => child.kill('SIGKILL'), 8000);
  t.after(() => { clearTimeout(deadline); if (child.exitCode === null && child.signalCode === null) child.kill('SIGKILL'); });
  const events: Event[] = [];
  let stderr = '';
  const listeners = new Set<() => void>();
  const output = createInterface({ input: child.stdout });
  output.on('line', line => { events.push(JSON.parse(line)); for (const notify of listeners) notify(); });
  child.stderr.setEncoding('utf8'); child.stderr.on('data', chunk => { stderr += chunk; });
  let closed = false;
  const completion = new Promise<{ code: number | null; stderr: string }>(resolve => child.once('close', code => {
    clearTimeout(deadline); closed = true; for (const notify of listeners) notify(); resolve({ code, stderr });
  }));
  const wait = (predicate: (events: Event[]) => boolean): Promise<void> => new Promise((resolve, reject) => {
    const timer = setTimeout(() => { listeners.delete(check); reject(new Error('The run did not emit the expected event.')); }, 5000);
    const check = (): void => {
      if (predicate(events)) { clearTimeout(timer); listeners.delete(check); resolve(); }
      else if (closed) { clearTimeout(timer); listeners.delete(check); reject(new Error(`The run ended before the expected event: ${JSON.stringify(events)} ${stderr}`)); }
    };
    listeners.add(check); check();
  });
  return { child, events, completion, wait };
}

test('run.lifecycle selects settings, sends exact instructions and cleans up its record', async t => {
  const f = await ready(t); const work = join(f.home, 'work'); await mkdir(work);
  await writeFile(join(f.home, '.arbol', 'arbol-codex-driver.json'), JSON.stringify({ toolPath: join(f.tool, 'codex'),
    subscriptions: { chatgpt: { defaultModel: 'gpt-6-astra', defaultEffort: 'high' } } }));
  const path = join(f.home, 'request.json'); const instructions = 'Exact instructions\nwith "quoted" text.\n';
  const original = JSON.stringify({ runId: 'fresh', tools: 'all', history: [], workingDirectory: work,
    systemPrompt: instructions, serviceTier: 'priority', labels: { exchange: '42' }, input: { role: 'user', text: 'hello' } });
  await writeFile(path, original);
  const result = await run(['run', '--request', path, '--state-dir', f.state], f.env);
  assert.equal(result.code, 0); assert.equal(result.stderr, '');
  const final = ordered(result.events, 'completed'); assert.equal(final.producedOutput, true); assert.deepEqual(final.unfinishedCalls, []);
  assert.equal(result.events[0]!.type, 'started'); assert.equal(result.events[0]!.continuity, 'fresh');
  assert.equal(result.events[0]!.model, 'gpt-6-astra'); assert.equal(result.events[0]!.effort, 'high');
  assert.ok(result.events.every(event => event.labels.exchange === '42'));
  const records = await received(f.tool);
  const thread = records.find(record => record.stage === 'request' && record.request.method === 'thread/start').request.params;
  assert.equal(thread.developerInstructions, instructions); assert.equal(thread.sandbox, 'danger-full-access');
  assert.equal(thread.approvalPolicy, 'never'); assert.equal(thread.ephemeral, undefined); assert.equal(thread.cwd, await realpath(work));
  const turn = records.find(record => record.stage === 'input').request.params;
  assert.equal(turn.model, 'gpt-6-astra'); assert.equal(turn.effort, 'high'); assert.equal(turn.serviceTier, 'priority');
  assert.equal(turn.summary, 'detailed'); assert.deepEqual(turn.sandboxPolicy, { type: 'dangerFullAccess' });
  assert.equal(records.filter(record => !record.stage && record.arguments[0] === 'app-server').length, 1);
  assert.equal(await readFile(path, 'utf8'), original); await cleaned(f.state, 'fresh'); assert.ok(await stat(work));
});

test('run.images creates private image files for localImage input and removes the temporary completion folder', async t => {
  const f = await ready(t); const path = join(f.home, 'request.json');
  await writeFile(path, JSON.stringify({ runId: 'images', tools: 'none', history: [], input: { role: 'user', text: 'hello',
    images: [{ mediaType: 'image/png', data: 'aQ==' }, { mediaType: 'image/webp', data: 'aGk=' }] } }));
  const result = await run(['run', '--request', path, '--state-dir', f.state], f.env);
  assert.equal(result.code, 0); ordered(result.events, 'completed');
  const records = await received(f.tool); const sent = records.find(record => record.stage === 'input');
  assert.deepEqual(sent.request.params.input.map((item: any) => item.type), ['text', 'localImage', 'localImage']);
  assert.deepEqual(sent.checks.images.map((image: any) => ({ data: image.data, mode: image.mode })), [
    { data: 'aQ==', mode: 0o600 }, { data: 'aGk=', mode: 0o600 },
  ]);
  const thread = records.find(record => record.stage === 'request' && record.request.method === 'thread/start').request.params;
  assert.equal(thread.ephemeral, true); assert.equal(thread.sandbox, 'read-only');
  assert.deepEqual(sent.request.params.sandboxPolicy, { type: 'readOnly', networkAccess: false });
  for (const image of sent.checks.images) await assert.rejects(stat(image.path), (error: any) => error.code === 'ENOENT');
  await assert.rejects(stat(thread.cwd), (error: any) => error.code === 'ENOENT'); await cleaned(f.state, 'images');
});

test('run.validation stops refusals before a thread starts, preserves labels and leaves no active records', async t => {
  const f = await ready(t); const path = join(f.home, 'request.json');
  for (const [id, fields, code] of [ ['missing-folder', { workingDirectory: join(f.home, 'missing') }, 'invalid_input'],
    ['bad-image', { input: { role: 'user', text: 'hello', images: [{ mediaType: 'application/pdf', data: 'aQ==' }] } }, 'invalid_input'],
    ['unknown-model', { model: 'unlisted-model' }, 'invalid_input'], ['unknown-effort', { effort: 'unlisted-effort' }, 'invalid_input'],
    ['unknown-tier', { serviceTier: 'unlisted-tier' }, 'invalid_input'], ['unknown-subscription', { subscriptionId: 'missing' }, 'not_found'],
  ] as const) {
    await writeFile(join(f.tool, 'received.jsonl'), '');
    await writeFile(path, JSON.stringify({ runId: id, tools: 'none', history: [], labels: { request: id }, input: { role: 'user', text: 'hello' }, ...fields }));
    const result = await run(['run', '--request', path, '--state-dir', f.state], f.env);
    assert.equal(result.code, 1, id); const final = ordered(result.events, 'failed'); assert.equal(final.error.code, code, id);
    assert.equal(result.events.length, 1, id); assert.deepEqual(final.labels, { request: id });
    const contents = await readFile(join(f.tool, 'received.jsonl'), 'utf8');
    if (contents.trim()) assert.equal((await received(f.tool)).some(record => record.request?.method === 'thread/start'), false, id);
    await cleaned(f.state, id);
  }
  const unsigned = await fixture(t);
  const result = await run(['run', '--run-id', 'signed-out', '--state-dir', unsigned.state, 'hello'], unsigned.env);
  assert.equal(ordered(result.events, 'failed').error.code, 'not_signed_in');
  await cleaned(unsigned.state, 'signed-out');
});

test('run.validation ignores an incompatible settings effort with a notice and refuses the same explicit effort', async t => {
  const f = await ready(t);
  await writeFile(join(f.home, '.arbol', 'arbol-codex-driver.json'), JSON.stringify({ toolPath: join(f.tool, 'codex'),
    subscriptions: { chatgpt: { defaultEffort: 'invalid-effort' } } }));
  const result = await run(['run', '--run-id', 'default-effort', '--state-dir', f.state, 'hello'], f.env);
  assert.equal(result.code, 0); ordered(result.events, 'completed');
  assert.ok(result.events.some(event => event.type === 'notice' && event.code === 'ignored_default_effort'));
  const turn = (await received(f.tool)).find(record => record.stage === 'input').request.params;
  assert.equal(turn.effort, 'low'); await cleaned(f.state, 'default-effort');
  await writeFile(join(f.tool, 'received.jsonl'), '');
  const explicit = await run(['run', '--run-id', 'explicit-effort', '--effort', 'invalid-effort', '--state-dir', f.state, 'hello'], f.env);
  assert.equal(explicit.code, 1); assert.equal(ordered(explicit.events, 'failed').error.code, 'invalid_input');
  assert.equal((await received(f.tool)).some(record => record.request?.method === 'thread/start'), false);
  await cleaned(f.state, 'explicit-effort');
});

test('run.validation rechecks the Codex account before starting a thread and marks a missing login as needing attention', async t => {
  const f = await ready(t);
  await unlink(join(f.state, 'subscriptions', 'chatgpt', 'home', 'auth.json'));
  const result = await run(['run', '--run-id', 'lost-login', '--state-dir', f.state, 'hello'], f.env);
  assert.equal(result.code, 1); assert.equal(ordered(result.events, 'failed').error.code, 'not_signed_in');
  assert.equal(result.events.length, 1);
  assert.equal((await received(f.tool)).some(record => record.request?.method === 'thread/start'), false);
  const subscription = JSON.parse(await readFile(join(f.state, 'subscriptions', 'chatgpt', 'record.json'), 'utf8'));
  assert.equal(subscription.state, 'needs_attention'); assert.equal(subscription.problem.code, 'credential_rejected');
  await cleaned(f.state, 'lost-login');
});

test('run.control reads a stdin request, refuses malformed and unmatched answers, then cancels on stop', async t => {
  const f = await ready(t, 'C33 hold'); const running = active(t, ['run', '--request', '-', '--control', '--state-dir', f.state], f.env);
  running.child.stdin.write(JSON.stringify({ runId: 'controlled', labels: { control: '42' }, history: [], tools: 'none', input: { role: 'user', text: 'hold' } }) + '\n');
  await running.wait(events => events.some(event => event.type === 'started'));
  running.child.stdin.write('not json\n' + JSON.stringify({ type: 'answer', askId: 'unknown', answer: {} }) + '\n');
  await running.wait(events => events.filter(event => event.type === 'control_refused').length === 2);
  const refusals = running.events.filter(event => event.type === 'control_refused');
  assert.equal(refusals[0]!.error.code, 'invalid_input'); assert.equal(refusals[1]!.error.code, 'not_found'); assert.equal(refusals[1]!.askId, 'unknown');
  running.child.stdin.write('{"type":"stop"}\n');
  const result = await running.completion; assert.equal(result.code, 2); ordered(running.events, 'cancelled');
  assert.ok(running.events.every(event => event.labels.control === '42')); await cleaned(f.state, 'controlled');
});

test('run.control cancels on stdin EOF and duplicate live identifiers are refused without affecting the first run', async t => {
  const f = await ready(t, 'C33 hold');
  const running = active(t, ['run', '--control', '--run-id', 'live', '--state-dir', f.state, 'hold'], f.env);
  await running.wait(events => events.some(event => event.type === 'started'));
  const second = await run(['run', '--run-id', 'live', '--state-dir', f.state, 'hello'], f.env);
  assert.equal(second.code, 1); assert.equal(ordered(second.events, 'failed').error.code, 'in_use');
  assert.ok(await stat(join(f.state, 'runs', 'live.json')));
  running.child.stdin.end(); assert.equal((await running.completion).code, 2); ordered(running.events, 'cancelled'); await cleaned(f.state, 'live');
});

test('run.control observes startup EOF and closes an open control reader after successful completion', async t => {
  const f = await ready(t);
  const ended = active(t, ['run', '--control', '--run-id', 'startup-eof', '--state-dir', f.state, 'hello'], f.env);
  ended.child.stdin.end();
  assert.equal((await ended.completion).code, 2); ordered(ended.events, 'cancelled'); await cleaned(f.state, 'startup-eof');
  assert.equal((await readFile(join(f.tool, 'received.jsonl'), 'utf8')).trim(), '');
  const completed = active(t, ['run', '--control', '--run-id', 'open-control', '--state-dir', f.state, 'hello'], f.env);
  assert.equal((await completed.completion).code, 0); ordered(completed.events, 'completed');
  await cleaned(f.state, 'open-control');
});

test('run.lifecycle ends the app-server and removes its record when the event consumer closes stdout', async t => {
  const f = await ready(t, 'C33 hold');
  const running = active(t, ['run', '--run-id', 'consumer-gone', '--state-dir', f.state, 'hold'], f.env);
  await running.wait(events => events.some(event => event.type === 'started'));
  const record = JSON.parse(await readFile(join(f.state, 'runs', 'consumer-gone.json'), 'utf8'));
  assert.equal(await ownerAlive(record.tool), true);
  running.child.stdout.destroy();
  assert.equal((await running.completion).code, 2);
  assert.equal(await ownerAlive(record.tool), false); await cleaned(f.state, 'consumer-gone');
});

test('run.unknown-request answers a future tool request immediately and keeps the run alive', async t => {
  const f = await ready(t); const result = await run(['run', '--run-id', 'unknown-request', '--state-dir', f.state, 'unknown-request'], f.env);
  assert.equal(result.code, 0); ordered(result.events, 'completed');
  assert.ok(result.events.some(event => event.type === 'notice' && event.code === 'unexpected_request'));
  const response = (await received(f.tool)).find(record => record.stage === 'response');
  assert.equal(response.request.id, 'fixture-server-request'); assert.equal(response.request.error.code, -32601);
  await cleaned(f.state, 'unknown-request');
});

test('run.failures preserve output and close unfinished calls without retrying a failed vendor or transport', async t => {
  for (const [scenario, message, id, code] of [ ['C12 plain', 'hello', 'vendor', 'vendor_error'],
    ['C42 plain', 'hello', 'dropped', 'tool_failed'], ['C43 malformed', 'hello', 'malformed', 'tool_failed'],
    ['C43 plain', 'early-exit', 'early-exit', 'tool_failed'] ] as const) {
    const f = await ready(t, scenario); const result = await run(['run', '--run-id', id, '--state-dir', f.state, message], f.env);
    assert.equal(result.code, 1, scenario); const final = ordered(result.events, 'failed'); assert.equal(final.error.code, code, scenario);
    const records = await received(f.tool);
    assert.equal(records.filter(record => !record.stage && record.arguments[0] === 'app-server').length, 1, scenario);
    if (scenario.startsWith('C42')) {
      assert.equal(final.producedOutput, true); assert.deepEqual(final.unfinishedCalls, ['fixture-call']);
      assert.ok(result.events.some(event => event.type === 'text' && event.text === 'answer'));
      const finished = result.events.filter(event => event.type === 'tool_finished'); assert.equal(finished.length, 1); assert.equal(finished[0]!.interrupted, true);
      assert.equal(final.usage.inputTokens, 3); assert.equal(final.usage.outputTokens, 2);
    }
    await cleaned(f.state, id);
  }
});

test('run.text prints authoritative text only and emits a final failure on CLI parsing errors', async t => {
  const f = await ready(t);
  const text = await exec(process.execPath, [cli, 'run', '--output', 'text', '--state-dir', f.state, 'hello'], { env: f.env, timeout: 10000 });
  assert.equal(text.stdout, 'answer'); assert.equal(text.stderr, '');
  const invalid = await run(['run', '--unknown'], f.env);
  assert.equal(invalid.code, 1); assert.equal(invalid.events.length, 1); assert.equal(ordered(invalid.events, 'failed').error.code, 'invalid_input');
});
