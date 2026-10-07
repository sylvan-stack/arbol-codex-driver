import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { TestContext } from 'node:test';
import { execFile, spawn } from 'node:child_process';
import { promisify } from 'node:util';
import { createInterface } from 'node:readline';
import { readFile, stat, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { fixture, cli, received } from './helpers.js';
import type { ProcessEnv } from '../src/types.js';
import { ownerAlive, processOwner } from '../src/state.js';
const exec = promisify(execFile);
type Event = { type: string; runId: string; seq: number; [key: string]: any };

async function ready(t: TestContext, part = 'tool') {
  const f = await fixture(t);
  await writeFile(join(f.tool, 'scenario'), 'C10 success');
  await exec(process.execPath, [cli, 'subscriptions', 'sign-in', 'chatgpt', '--state-dir', f.state], { env: f.env, timeout: 10000 });
  await writeFile(join(f.tool, 'scenario'), 'C15 ' + part);
  await writeFile(join(f.tool, 'received.jsonl'), '');
  return f;
}
async function completeRecords(tool: string): Promise<any[]> {
  const text = await readFile(join(tool, 'received.jsonl'), 'utf8');
  return text.split('\n').slice(0, -1).filter(Boolean).map(line => JSON.parse(line));
}
function active(t: TestContext, env: ProcessEnv, state: string, id: string, control = true) {
  const child = spawn(process.execPath, [cli, 'run', '--state-dir', state, '--run-id', id,
    '--subscription', 'chatgpt', '--tools', 'all', '--cwd', env.HOME!, ...(control ? ['--control'] : []), 'answer'], { env, stdio: 'pipe' });
  child.stdin.on('error', () => {});
  let stderr = '', closed = false;
  const events: Event[] = [];
  const listeners = new Set<() => void>();
  const timer = setTimeout(() => child.kill('SIGKILL'), 18000);
  t.after(() => { clearTimeout(timer); if (child.exitCode === null && child.signalCode === null) child.kill('SIGKILL'); });
  createInterface({ input: child.stdout }).on('line', line => {
    events.push(JSON.parse(line)); for (const notify of listeners) notify();
  });
  child.stderr.setEncoding('utf8'); child.stderr.on('data', chunk => { stderr += chunk; });
  const done = new Promise<{ code: number | null; stderr: string }>(resolve => child.once('close', code => {
    clearTimeout(timer); closed = true; for (const notify of listeners) notify(); resolve({ code, stderr });
  }));
  const wait = (predicate: (events: Event[]) => boolean, deadline = 5000): Promise<void> => new Promise((resolve, reject) => {
    const timer = setTimeout(() => { listeners.delete(check); reject(new Error('Expected stopping event did not arrive: ' + JSON.stringify(events))); }, deadline);
    const check = (): void => {
      if (predicate(events)) { clearTimeout(timer); listeners.delete(check); resolve(); }
      else if (closed) { clearTimeout(timer); listeners.delete(check); reject(new Error('Run ended before expected stopping event: ' + JSON.stringify(events) + stderr)); }
    };
    listeners.add(check); check();
  });
  return { child, events, done, wait };
}
function final(events: Event[], outcome = 'cancelled'): Event {
  assert.deepEqual(events.map(event => event.seq), events.map((_, index) => index + 1));
  assert.equal(events.filter(event => event.type === 'finished').length, 1);
  assert.equal(events.at(-1)!.type, 'finished'); assert.equal(events.at(-1)!.outcome, outcome);
  assert.ok(events.every(event => event.runId === events[0]!.runId));
  for (const call of events.filter(event => event.type === 'tool_started')) {
    assert.equal(events.filter(event => event.type === 'tool_finished' && event.callId === call.callId).length, 1);
  }
  return events.at(-1)!;
}
async function cleaned(state: string, id: string): Promise<void> {
  for (const file of [join(state, 'runs', id + '.json'), join(state, 'tmp', id)]) {
    await assert.rejects(stat(file), (error: any) => error.code === 'ENOENT');
  }
}
async function workerOwners(t: TestContext, tool: string) {
  const input = (await received(tool)).find(record => record.stage === 'input');
  assert.ok(input, 'The fixture must record its accepted turn.');
  const owners = await Promise.all(['toolPid', 'shellPid', 'backgroundPid'].map(key => processOwner(input.checks[key])));
  assert.ok(owners.every(owner => owner), 'The tool and both shell group processes were alive before stopping.');
  t.after(async () => {
    for (const owner of owners) if (owner && await ownerAlive(owner)) {
      try { process.kill(owner.pid, 'SIGKILL'); } catch { /* already gone */ }
    }
  });
  return { input, owners };
}
async function workersGone(owners: Awaited<ReturnType<typeof workerOwners>>['owners']): Promise<void> {
  for (const owner of owners) assert.equal(await ownerAlive(owner!), false, 'No process remains after the final event.');
}

test('stop.paths interrupts the native turn and cleans shell groups for control, signals, EOF and runs stop', async t => {
  for (const path of ['control', 'SIGINT', 'SIGTERM', 'EOF', 'runs-stop'] as const) await t.test(path, async t => {
    const f = await ready(t); const id = 'stop-' + path.toLowerCase();
    const running = active(t, f.env, f.state, id, path !== 'runs-stop');
    await running.wait(events => events.some(event => event.type === 'tool_started'));
    const workers = await workerOwners(t, f.tool);
    const start = performance.now();
    if (path === 'control') running.child.stdin.write('{"type":"stop"}\n{"type":"stop"}\n');
    else if (path === 'EOF') running.child.stdin.end();
    else if (path === 'runs-stop') {
      const stopped = await exec(process.execPath, [cli, 'runs', 'stop', id, '--state-dir', f.state], { env: f.env, timeout: 20000 });
      assert.equal(stopped.stdout, ''); assert.equal(stopped.stderr, '');
    } else running.child.kill(path);
    const result = await running.done;
    assert.equal(result.code, 2); assert.equal(result.stderr, ''); assert.ok(performance.now() - start < 15000);
    const ended = final(running.events);
    assert.equal(ended.producedOutput, true); assert.equal(ended.usage.inputTokens, 3); assert.equal(ended.usage.outputTokens, 2);
    assert.equal(running.events.find(event => event.type === 'text_delta')!.text, 'partial');
    assert.equal(running.events.find(event => event.type === 'tool_finished')!.interrupted, true);
    const interrupts = (await received(f.tool)).filter(record => record.stage === 'interrupt');
    assert.equal(interrupts.length, 1); assert.deepEqual(interrupts[0].request.params, { threadId: 'fixture-thread', turnId: 'fixture-turn' });
    await workersGone(workers.owners); await cleaned(f.state, id);
  });
});

test('stop.output a broken event pipe cancels with native interrupt and leaves no tool or shell worker', async t => {
  const f = await ready(t); const running = active(t, f.env, f.state, 'pipe');
  await running.wait(events => events.some(event => event.type === 'tool_started'));
  const workers = await workerOwners(t, f.tool);
  running.child.stdout.destroy();
  running.child.stdin.write('{"type":"unknown"}\n');
  assert.equal((await running.done).code, 2);
  assert.ok((await received(f.tool)).some(record => record.stage === 'interrupt'));
  await workersGone(workers.owners); await cleaned(f.state, 'pipe');
});

test('stop.startup a control stop before startup finishes once and sends no inference', async t => {
  const f = await ready(t); const running = active(t, f.env, f.state, 'early');
  running.child.stdin.write('{"type":"stop"}\n');
  assert.equal((await running.done).code, 2); final(running.events);
  assert.equal((await readFile(join(f.tool, 'received.jsonl'), 'utf8')).trim(), '');
  await cleaned(f.state, 'early');
});

test('stop.stdin-request cancels a pending first request line while its input remains open', async t => {
  for (const control of [false, true]) await t.test(control ? 'control' : 'no-control', async t => {
    const f = await fixture(t); f.env.ARBOL_TEST_TIME_SCALE = '10';
    const child = spawn(process.execPath, [cli, 'run', '--request', '-', ...(control ? ['--control'] : []), '--state-dir', f.state], { env: f.env, stdio: 'pipe' });
    const events: Event[] = []; let stderr = '';
    child.stdin.on('error', () => {}); createInterface({ input: child.stdout }).on('line', line => events.push(JSON.parse(line)));
    child.stderr.setEncoding('utf8'); child.stderr.on('data', chunk => { stderr += chunk; });
    const timer = setTimeout(() => child.kill('SIGKILL'), 3000);
    t.after(() => { clearTimeout(timer); if (child.exitCode === null && child.signalCode === null) child.kill('SIGKILL'); child.stdin.destroy(); });
    const done = new Promise<number | null>(resolve => child.once('close', code => { clearTimeout(timer); resolve(code); }));
    const deadline = performance.now() + 2000;
    while (!await stat(join(f.state, 'format')).then(() => true).catch(() => false)) {
      assert.ok(performance.now() < deadline); await new Promise(resolve => setTimeout(resolve, 10));
    }
    // Supply no request JSON and keep stdin open; only the signal can release it.
    await new Promise(resolve => setTimeout(resolve, 30)); const start = performance.now(); child.kill('SIGTERM');
    assert.equal(await done, 2); assert.ok(performance.now() - start < 1500); assert.equal(stderr, '');
    final(events); assert.equal(events.length, 1);
    const log = await readFile(join(f.tool, 'received.jsonl'), 'utf8').catch(() => ''); assert.equal(log.trim(), '');
  });
});

test('stop.stdin-request-eof cancels when a controlled stdin request closes before its first line', async t => {
  const f = await fixture(t); f.env.ARBOL_TEST_TIME_SCALE = '10';
  const child = spawn(process.execPath, [cli, 'run', '--request', '-', '--control', '--state-dir', f.state], { env: f.env, stdio: 'pipe' });
  const events: Event[] = []; let stderr = '';
  child.stdin.on('error', () => {}); createInterface({ input: child.stdout }).on('line', line => events.push(JSON.parse(line)));
  child.stderr.setEncoding('utf8'); child.stderr.on('data', chunk => { stderr += chunk; });
  const timer = setTimeout(() => child.kill('SIGKILL'), 3000);
  t.after(() => { clearTimeout(timer); if (child.exitCode === null && child.signalCode === null) child.kill('SIGKILL'); });
  const done = new Promise<number | null>(resolve => child.once('close', code => { clearTimeout(timer); resolve(code); }));
  child.stdin.end(); assert.equal(await done, 2); assert.equal(stderr, ''); final(events); assert.equal(events.length, 1);
  const log = await readFile(join(f.tool, 'received.jsonl'), 'utf8').catch(() => ''); assert.equal(log.trim(), '');
});

test('stop.stubborn gives an ignored interrupt two seconds before ending the process and shell group', async t => {
  const f = await ready(t, 'stubborn'); const running = active(t, f.env, f.state, 'stubborn');
  await running.wait(events => events.some(event => event.type === 'tool_started'));
  const workers = await workerOwners(t, f.tool); const start = performance.now();
  running.child.stdin.write('{"type":"stop"}\n');
  assert.equal((await running.done).code, 2);
  const elapsed = performance.now() - start; assert.ok(elapsed >= 1900 && elapsed < 3500, `Ignored interrupt, EOF and SIGTERM lasted ${elapsed} ms.`);
  final(running.events); await workersGone(workers.owners); await cleaned(f.state, 'stubborn');
});

test('stop.shutdown anchors forced cleanup to a caller stop received while normal EOF cleanup is pending', async t => {
  for (const path of ['SIGTERM', 'control', 'EOF'] as const) await t.test(path, async t => {
    const id = 'eof-' + path.toLowerCase();
    const f = await ready(t, 'linger'); const running = active(t, f.env, f.state, id, path !== 'SIGTERM');
    await running.wait(events => events.some(event => event.type === 'text'));
    const workers = await workerOwners(t, f.tool);
    const deadline = performance.now() + 3000;
    while (!(await completeRecords(f.tool)).some(record => record.stage === 'stdinEOF')) {
      assert.ok(performance.now() < deadline, 'The vendor must receive EOF before caller cancellation.');
      await new Promise(resolve => setTimeout(resolve, 5));
    }
    await new Promise(resolve => setTimeout(resolve, 100));
    assert.equal(await ownerAlive(workers.owners[0]!), true);
    const stoppedAt = performance.now();
    if (path === 'control') running.child.stdin.write('{"type":"stop"}\n');
    else if (path === 'EOF') running.child.stdin.end();
    else running.child.kill('SIGTERM');
    assert.equal((await running.done).code, 2);
    const elapsed = performance.now() - stoppedAt;
    assert.ok(elapsed >= 1900 && elapsed < 3500, `EOF cleanup must keep the caller stop deadline: ${elapsed} ms.`);
    final(running.events); await workersGone(workers.owners); await cleaned(f.state, id);
    assert.equal((await completeRecords(f.tool)).filter(record => record.stage === 'interrupt').length, 0);
  });
});

test('stop.subagent interrupts an active child turn after the main turn completed and preserves its parent attribution', async t => {
  const f = await ready(t, 'subagent-finished'); const running = active(t, f.env, f.state, 'child');
  await running.wait(events => events.some(event => event.parentCallId && event.type === 'tool_started'));
  const workers = await workerOwners(t, f.tool);
  running.child.stdin.write('{"type":"stop"}\n');
  assert.equal((await running.done).code, 2); final(running.events);
  const interrupts = (await received(f.tool)).filter(record => record.stage === 'interrupt');
  assert.deepEqual(interrupts.map(record => record.request.params), [{ threadId: 'fixture-subagent-thread', turnId: 'fixture-subagent-turn' }]);
  const child = running.events.filter(event => event.parentCallId);
  assert.ok(child.some(event => event.type === 'text_delta' && event.text === 'child-only'));
  assert.ok(child.every(event => event.parentCallId === 'fixture-subagent-thread'));
  assert.ok(running.events.filter(event => event.type === 'text' && !event.parentCallId).every(event => event.text !== 'child-only'));
  assert.equal(child.find(event => event.type === 'tool_finished')!.interrupted, true);
  await workersGone(workers.owners); await cleaned(f.state, 'child');
});

test('stop.subagent-completion waits for the child after the main turn and closes spawn once before the final event', async t => {
  const f = await ready(t, 'subagent-late'); const running = active(t, f.env, f.state, 'late-child');
  await running.wait(events => events.some(event => event.parentCallId && event.type === 'tool_started'));
  const workers = await workerOwners(t, f.tool);
  assert.equal((await running.done).code, 0); final(running.events, 'completed');
  assert.equal(running.events.find(event => event.type === 'tool_finished' && event.callId === 'fixture-subcall')!.ok, true);
  assert.ok(running.events.some(event => event.type === 'text' && event.parentCallId === 'fixture-subagent-thread' && event.text === 'child-only'));
  assert.equal(running.events.filter(event => event.type === 'tool_finished' && event.callId === 'fixture-subagent-thread').length, 1);
  await workersGone(workers.owners); await cleaned(f.state, 'late-child');
});

test('stop.nested-subagents interrupts every active descendant turn and attributes nested calls', async t => {
  const f = await ready(t, 'subagent-nested'); const running = active(t, f.env, f.state, 'nested');
  await running.wait(events => events.some(event => event.callId === 'fixture-grandcall' && event.type === 'tool_started'));
  const workers = await workerOwners(t, f.tool);
  running.child.stdin.write('{"type":"stop"}\n');
  assert.equal((await running.done).code, 2); const ended = final(running.events);
  const interrupts = (await received(f.tool)).filter(record => record.stage === 'interrupt').map(record => record.request.params.threadId).sort();
  assert.deepEqual(interrupts, ['fixture-grandchild-thread', 'fixture-subagent-thread', 'fixture-thread']);
  assert.equal(running.events.find(event => event.type === 'text_delta' && event.text === 'grandchild-only')!.parentCallId, 'fixture-grandchild-thread');
  assert.equal(running.events.find(event => event.type === 'tool_finished' && event.callId === 'fixture-grandcall')!.parentCallId, 'fixture-grandchild-thread');
  assert.ok(ended.unfinishedCalls.includes('fixture-grandcall'));
  await workersGone(workers.owners); await cleaned(f.state, 'nested');
});

test('stop.accepted-turn interrupts a turn announced before its delayed turn/start reply', async t => {
  const f = await ready(t, 'turn-start-race'); const running = active(t, f.env, f.state, 'accepted');
  const deadline = performance.now() + 5000;
  while (!(await completeRecords(f.tool)).some(record => record.stage === 'accepted-turn')) {
    assert.ok(performance.now() < deadline, 'The server must accept a turn before the stop.');
    await new Promise(resolve => setTimeout(resolve, 5));
  }
  const workers = await workerOwners(t, f.tool);
  running.child.stdin.write('{"type":"stop"}\n');
  assert.equal((await running.done).code, 2); final(running.events);
  assert.ok((await received(f.tool)).some(record => record.stage === 'interrupt' && record.request.params.threadId === 'fixture-thread'));
  await workersGone(workers.owners); await cleaned(f.state, 'accepted');
});

test('stop.late-subagent-turn discovers and interrupts a child turn announced after the main interrupt', async t => {
  const f = await ready(t, 'subagent-discovery'); const running = active(t, f.env, f.state, 'discovery');
  await running.wait(events => events.some(event => event.type === 'tool_started' && event.name === 'spawn_agent'));
  const workers = await workerOwners(t, f.tool);
  assert.equal(running.events.some(event => event.callId === 'fixture-subcall'), false);
  running.child.stdin.write('{"type":"stop"}\n');
  assert.equal((await running.done).code, 2); final(running.events);
  const interrupts = (await received(f.tool)).filter(record => record.stage === 'interrupt').map(record => record.request.params.threadId).sort();
  assert.deepEqual(interrupts, ['fixture-subagent-thread', 'fixture-thread']);
  assert.equal(running.events.find(event => event.type === 'tool_finished' && event.callId === 'fixture-subcall')!.interrupted, true);
  await workersGone(workers.owners); await cleaned(f.state, 'discovery');
});

test('stop.collaboration-spawn discovers a child from spawnAgent receivers and recovers its early turn announcement', async t => {
  const f = await ready(t, 'subagent-collab'); const running = active(t, f.env, f.state, 'collab');
  await running.wait(events => events.some(event => event.type === 'tool_started' && event.callId === 'fixture-subcall' && event.parentCallId));
  const workers = await workerOwners(t, f.tool); running.child.stdin.write('{"type":"stop"}\n');
  assert.equal((await running.done).code, 2); final(running.events);
  const interrupts = (await received(f.tool)).filter(record => record.stage === 'interrupt').map(record => record.request.params.threadId).sort();
  assert.deepEqual(interrupts, ['fixture-subagent-thread', 'fixture-thread']);
  assert.equal(running.events.find(event => event.type === 'tool_finished' && event.callId === 'fixture-subcall')!.interrupted, true);
  assert.ok(running.events.some(event => event.type === 'text_delta' && event.text === 'child-only' && event.parentCallId === 'fixture-spawn-call'));
  await workersGone(workers.owners); await cleaned(f.state, 'collab');
});

test('stop.late-collaboration-spawn waits for a pending spawn to identify its child after the main interrupt', async t => {
  const f = await ready(t, 'subagent-collab-discovery'); const running = active(t, f.env, f.state, 'late-collab');
  await running.wait(events => events.some(event => event.type === 'tool_started' && event.name === 'spawnAgent'));
  const workers = await workerOwners(t, f.tool);
  assert.equal(running.events.some(event => event.callId === 'fixture-subcall'), false);
  running.child.stdin.write('{"type":"stop"}\n'); assert.equal((await running.done).code, 2); final(running.events);
  const interrupts = (await received(f.tool)).filter(record => record.stage === 'interrupt').map(record => record.request.params.threadId).sort();
  assert.deepEqual(interrupts, ['fixture-subagent-thread', 'fixture-thread']);
  assert.equal(running.events.find(event => event.type === 'tool_finished' && event.callId === 'fixture-subcall')!.parentCallId, 'fixture-spawn-call');
  await workersGone(workers.owners); await cleaned(f.state, 'late-collab');
});

test('stop.other-call waits up to two seconds for an unfinished non-command call after turn completion', async t => {
  const f = await ready(t, 'other-call'); const running = active(t, f.env, f.state, 'other-call');
  await running.wait(events => events.some(event => event.type === 'text' && event.text === 'answer'));
  const start = performance.now();
  assert.equal((await running.done).code, 0); const ended = final(running.events, 'completed');
  assert.ok(performance.now() - start >= 1800);
  assert.deepEqual(ended.unfinishedCalls, ['fixture-other-call']);
  assert.equal(running.events.find(event => event.type === 'tool_finished')!.interrupted, true);
  await cleaned(f.state, 'other-call');
});
