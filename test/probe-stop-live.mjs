// Opt-in: three short cancellation checks using the signed-in test account.
// Nothing signs in, copies credentials or changes the test login.
import assert from 'node:assert/strict';
import { execFile, spawn } from 'node:child_process';
import { createInterface } from 'node:readline';
import { mkdtemp, mkdir, readFile, realpath, rm, stat, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { promisify } from 'node:util';
import { collectProcessGroups } from '../dist/src/process-groups.js';
import { ownerAlive } from '../dist/src/state.js';
if (process.argv.length !== 5 && !(process.argv.length === 7 && process.argv[5] === '--case' && process.argv[6] === 'subagent')) {
  throw new Error('Usage: probe-stop-live.mjs <codex-path> <state-dir> <record-path> [--case subagent]');
}
const selectedCase = process.argv[6];
const exec = promisify(execFile);
const toolPath = resolve(process.argv[2]); const state = resolve(process.argv[3]); const output = resolve(process.argv[4]);
const cli = resolve(import.meta.dirname, '../bin/arbol-codex-driver.mjs');
const scratch = await realpath(await mkdtemp(join(tmpdir(), 'syl89-live-'))); const cwd = join(scratch, 'work');
const env = { HOME: scratch, PATH: `${dirname(process.execPath)}:/opt/homebrew/bin:/usr/bin:/bin`, LANG: 'C', TMPDIR: scratch };
const safe = value => JSON.parse(JSON.stringify(value).replaceAll(scratch, '<live-home>'));
const record = { check: 'live.stopping', date: new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Madrid',
  year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date()), node: process.version,
  subscription: 'test-chatgpt', accountHomeUsedDirectly: true, ...(selectedCase ? { selectedCase } : {}), promptCount: 0, runs: [] };
const children = [];
try {
  await mkdir(cwd); await mkdir(join(scratch, '.arbol'));
  await writeFile(join(scratch, '.arbol', 'arbol-codex-driver.json'), JSON.stringify({ toolPath }), { mode: 0o600 });
  const invoke = async args => (await exec(process.execPath, [cli, '--state-dir', state, ...args], { env, timeout: 30000, maxBuffer: 2 * 1024 * 1024 })).stdout;
  record.toolVersion = JSON.parse(await invoke(['info'])).tool.version;
  record.usageBefore = JSON.parse(await invoke(['subscriptions', 'usage', 'test-chatgpt']));
  assert.equal(record.usageBefore.outcome, 'ok');
  assert.ok(!record.usageBefore.windows.some(window => window.limitReached || window.usedPercent >= 100));
  const models = JSON.parse(await invoke(['subscriptions', 'models', 'test-chatgpt']));
  const model = models.models.find(item => item.id === 'gpt-5.6-luna') ?? models.models.find(item => item.id === 'gpt-6-luna');
  assert.ok(model, 'Use a Luna test model.');
  const effort = ['minimal', 'low', 'medium', 'high', 'xhigh'].find(value => model.efforts.includes(value)); assert.ok(effort);
  record.model = model.id; record.effort = effort;
  const cases = [
    { id: 'text', tools: 'none', prompt: 'Output the integers from 1 through 10000, one per line. Begin immediately. Do not use tools.',
      ready: event => event.type === 'text_delta' },
    { id: 'orphan', tools: 'all', prompt: 'Run exactly one terminal command: sleep 90; printf SHOULD_NOT_FINISH. Wait for it, then reply DONE.',
      ready: event => event.type === 'tool_started' && event.name === 'shell' && JSON.stringify(event.input).includes('sleep 90') },
    { id: 'subagent', tools: 'all', prompt: 'Start exactly one sub-agent. Its only task is to run the terminal command sleep 90; printf CHILD_SHOULD_NOT_FINISH and report the output. Wait for the sub-agent, then reply DONE.',
      ready: event => event.type === 'tool_started' && event.name === 'shell' && event.parentCallId && JSON.stringify(event.input).includes('sleep 90') },
  ];
  for (const check of cases.filter(check => !selectedCase || check.id === selectedCase)) {
    const id = `syl89-live-${check.id}-${Date.now()}`; const file = join(scratch, check.id + '.json');
    const request = { runId: id, subscriptionId: 'test-chatgpt', model: model.id, effort, tools: check.tools,
      ...(check.tools === 'all' ? { workingDirectory: cwd } : {}), history: [],
      systemPrompt: 'Follow the user request precisely. Keep your own messages short.', input: { role: 'user', text: check.prompt }, labels: { check: 'live.stopping' } };
    await writeFile(file, JSON.stringify(request), { mode: 0o600 });
    const events = []; let stderr = '', closed = false;
    const listeners = new Set();
    const child = spawn(process.execPath, [cli, 'run', '--request', file, '--control', '--state-dir', state], { env, stdio: 'pipe' }); children.push(child);
    const run = { id: check.id, runId: id, input: request.input, events }; record.runs.push(run); record.promptCount++;
    const timer = setTimeout(() => child.kill('SIGTERM'), 100000);
    child.stdin.on('error', () => {});
    createInterface({ input: child.stdout }).on('line', line => { events.push(JSON.parse(line)); for (const notify of listeners) notify(); });
    child.stderr.setEncoding('utf8'); child.stderr.on('data', chunk => { stderr += chunk; });
    const done = new Promise(resolve => child.once('close', (code, signal) => { clearTimeout(timer); closed = true; run.signal = signal; for (const notify of listeners) notify(); resolve(code); }));
    const target = new Promise((resolve, reject) => {
      const timer = setTimeout(() => { listeners.delete(test); reject(new Error(`The ${check.id} check did not reach its cancellation point within sixty seconds.`)); }, 60000);
      const test = () => {
        if (events.some(check.ready)) { clearTimeout(timer); listeners.delete(test); resolve(); }
        else if (closed) { clearTimeout(timer); listeners.delete(test); reject(new Error(`The ${check.id} check ended before its cancellation point: ${JSON.stringify(events.at(-1))}`)); }
      };
      listeners.add(test); test();
    });
    try {
      await target;
      const active = JSON.parse(await readFile(join(state, 'runs', id + '.json'), 'utf8'));
      const groups = await collectProcessGroups(active.tool); run.processGroupsBefore = groups;
      assert.ok(groups.length >= 1); assert.equal(await ownerAlive(active.tool), true);
      const start = performance.now();
      if (check.id === 'orphan') {
        child.kill('SIGKILL'); run.code = await done; assert.equal(run.code, null); assert.equal(run.signal, 'SIGKILL');
        const listed = JSON.parse(await invoke(['runs', 'list'])); assert.ok(!listed.some(item => item.runId === id));
        run.recoveryElapsedMs = Math.round(performance.now() - start); assert.ok(run.recoveryElapsedMs < 20000);
        assert.equal(events.some(event => event.type === 'finished'), false); run.killedDriverRecovered = true;
      } else {
        child.stdin.write('{"type":"stop"}\n'); run.code = await done; run.stopElapsedMs = Math.round(performance.now() - start);
        assert.equal(run.code, 2); assert.equal(stderr, ''); assert.ok(run.stopElapsedMs < 15000);
        events.forEach((event, index) => assert.equal(event.seq, index + 1));
        assert.equal(events.filter(event => event.type === 'finished').length, 1); assert.equal(events.at(-1)?.outcome, 'cancelled');
        for (const call of events.filter(event => event.type === 'tool_started')) assert.equal(events.filter(event => event.type === 'tool_finished' && event.callId === call.callId).length, 1);
        if (check.id !== 'text') assert.ok(events.some(event => event.type === 'tool_finished' && event.interrupted));
        if (check.id === 'subagent') {
          assert.ok(events.some(event => event.type === 'tool_started' && ['spawn_agent', 'spawnAgent'].includes(event.name)));
          assert.ok(events.some(event => event.type === 'tool_finished' && event.parentCallId && event.interrupted));
        }
      }
      for (const group of groups) {
        assert.equal(await ownerAlive(group), false); assert.deepEqual(await collectProcessGroups(group), []);
      }
      for (const path of [join(state, 'runs', id + '.json'), join(state, 'tmp', id)]) await assert.rejects(stat(path), error => error.code === 'ENOENT');
      run.groupsAbsentAfterFinalOrRecovery = true; run.recordAndScratchRemoved = true; run.checksPassed = true;
    } finally {
      if (!closed) { child.stdin.write('{"type":"stop"}\n'); child.kill('SIGTERM'); await done; }
      clearTimeout(timer);
    }
  }
  record.usageAfter = JSON.parse(await invoke(['subscriptions', 'usage', 'test-chatgpt'])); record.checksPassed = true;
} catch (error) { record.checksPassed = false; record.failure = error.message; throw error; }
finally {
  for (const child of children) if (child.exitCode === null && child.signalCode === null) child.kill('SIGTERM');
  await mkdir(dirname(output), { recursive: true }); await writeFile(output, JSON.stringify(safe(record), null, 2) + '\n');
  await rm(scratch, { recursive: true, force: true });
}
process.stdout.write(JSON.stringify({ check: record.check, toolVersion: record.toolVersion, promptCount: record.promptCount,
  model: record.model, effort: record.effort, runs: record.runs.map(run => ({ id: run.id, stopElapsedMs: run.stopElapsedMs,
    recoveryElapsedMs: run.recoveryElapsedMs, checksPassed: run.checksPassed })), output }) + '\n');
