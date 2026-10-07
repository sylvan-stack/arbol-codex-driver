// Opt-in: four short turns on the already signed-in test-chatgpt account.
import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdtemp, mkdir, readFile, readdir, realpath, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { basename, dirname, join, resolve } from 'node:path';
import { promisify } from 'node:util';
const exec = promisify(execFile);
const toolPath = resolve(process.argv[2]);
const state = resolve(process.argv[3]);
const output = resolve(process.argv[4]);
const cli = resolve(import.meta.dirname, '../bin/arbol-codex-driver.mjs');
const scratch = await mkdtemp(join(tmpdir(), 'syl88-live-'));
const env = { HOME: scratch, PATH: `${dirname(process.execPath)}:/opt/homebrew/bin:/usr/bin:/bin`, LANG: 'C', TMPDIR: scratch };
const resumeRecord = process.argv[5] === '--continue-record' ? JSON.parse(await readFile(output, 'utf8')) : undefined;
if (resumeRecord) assert.equal(resumeRecord.runs.length, 3, 'Continue only after the first three completed turns.');
if (resumeRecord) {
  assert.equal(await realpath(dirname(dirname(resumeRecord.workingDirectory))), await realpath(tmpdir()));
  assert.ok(basename(dirname(resumeRecord.workingDirectory)).startsWith('syl88-live-'));
  assert.equal(basename(resumeRecord.workingDirectory), 'work');
}
const evidence = resumeRecord ?? { check: 'live.continuity', date: new Date().toISOString().slice(0, 10), node: process.version,
  subscription: 'test-chatgpt', accountHomeUsedDirectly: true, environmentNames: Object.keys(env).sort(), promptCount: 0, runs: [] };
try {
  await mkdir(join(scratch, '.arbol'));
  await writeFile(join(scratch, '.arbol', 'arbol-codex-driver.json'), JSON.stringify({ toolPath }), { mode: 0o600 });
  const invoke = async args => (await exec(process.execPath, [cli, '--state-dir', state, ...args], { env, timeout: 90000, maxBuffer: 2 * 1024 * 1024 })).stdout;
  evidence.toolVersion = JSON.parse(await invoke(['info'])).tool.version;
  evidence.usageBefore = JSON.parse(await invoke(['subscriptions', 'usage', 'test-chatgpt']));
  assert.equal(evidence.usageBefore.outcome, 'ok');
  assert.ok(!evidence.usageBefore.windows.some(window => window.limitReached || window.usedPercent >= 100));
  const models = JSON.parse(await invoke(['subscriptions', 'models', 'test-chatgpt']));
  const model = models.models.find(item => item.id === 'gpt-5.6-luna') ?? models.models.find(item => item.id === 'gpt-6-luna');
  assert.ok(model, 'Use a Luna test model.');
  const effort = ['minimal', 'low', 'medium', 'high', 'xhigh'].find(value => model.efforts.includes(value));
  assert.ok(effort);
  const work = resumeRecord?.workingDirectory ?? join(scratch, 'work'); await mkdir(work, { recursive: true });
  const chatSessionId = resumeRecord?.chatSessionId ?? `syl88-live-${Date.now()}`;
  evidence.chatSessionId = chatSessionId; evidence.workingDirectory = work;
  const base = { subscriptionId: 'test-chatgpt', model: model.id, effort, tools: 'all', workingDirectory: work, chatSessionId,
    systemPrompt: 'Follow the user request precisely. Keep every answer short.' };
  const run = async (id, fields, continuity, reason) => {
    const request = { ...base, ...fields, runId: id, labels: { check: 'live.continuity' } };
    if (resumeRecord) {
      const recorded = evidence.runs.find(item => item.id === id);
      if (recorded) {
        assert.equal(recorded.events.at(-1).outcome, 'completed');
        return { events: recorded.events, input: request.input,
          answer: recorded.events.filter(event => event.type === 'text').map(event => event.text).join('') };
      }
    }
    const file = join(scratch, id + '.json'); const original = JSON.stringify(request);
    await writeFile(file, original, { mode: 0o600 });
    evidence.promptCount++;
    const text = await invoke(['run', '--request', file]);
    const events = text.trim().split('\n').map(line => JSON.parse(line));
    evidence.runs.push({ id, continuity, reason, events });
    assert.equal(events[0].type, 'started'); assert.equal(events[0].continuity, continuity);
    assert.equal(events[0].rebuildReason, reason);
    events.forEach((event, index) => assert.equal(event.seq, index + 1));
    assert.equal(events.filter(event => event.type === 'finished').length, 1);
    assert.equal(events.at(-1).outcome, 'completed');
    assert.equal(await readFile(file, 'utf8'), original);
    await assert.rejects(readFile(join(state, 'runs', id + '.json')));
    await assert.rejects(readdir(join(state, 'tmp', id)));
    assert.ok(!events.some(event => event.code === 'history_as_text'), 'The installed tool must accept native history.');
    return { events, input: request.input, answer: events.filter(event => event.type === 'text').map(event => event.text).join('') };
  };
  const first = await run('syl88-live-first', { history: [], input: { role: 'user', text:
    'Remember code word ARBOL_FIRST. Run the terminal command printf ARBOL_TRAIL exactly once. Then reply exactly DONE.' } }, 'fresh');
  assert.equal(first.answer.trim(), 'DONE');
  const history = [{ type: 'message', ...first.input }];
  const calls = new Map();
  for (const event of first.events) {
    if (event.type === 'tool_started') calls.set(event.callId, event);
    if (event.type === 'tool_finished') {
      const started = calls.get(event.callId); assert.ok(started);
      history.push({ type: 'tool_call', name: started.name, input: started.input, ok: event.ok,
        ...(event.result === undefined ? {} : { result: event.result }), ...(event.error === undefined ? {} : { error: event.error }) });
    }
    if (event.type === 'text') history.push({ type: 'message', role: 'assistant', text: event.text });
  }
  assert.ok(history.some(item => item.type === 'tool_call' && item.name === 'shell' && item.result.output.includes('ARBOL_TRAIL')));
  const second = await run('syl88-live-second', { history, input: { role: 'user', text:
    'Use no tools. What code word did I ask you to remember, and what did the terminal print? Answer exactly ARBOL_FIRST / ARBOL_TRAIL.' } }, 'resumed');
  assert.equal(second.answer.trim(), 'ARBOL_FIRST / ARBOL_TRAIL');
  const edited = history.map((item, index) => index === 0 ? { ...item, text: item.text.replace('ARBOL_FIRST', 'ARBOL_EDITED') } : item);
  const third = await run('syl88-live-edited', { history: edited, input: { role: 'user', text:
    'Use no tools. From earlier history only, report the remembered code word, terminal output, and exact historical tool name. Answer as word / output / tool.' } }, 'rebuilt', 'history_differs');
  assert.match(third.answer, /ARBOL_EDITED\s*\/\s*ARBOL_TRAIL\s*\/\s*(shell|exec_command|exec)\s*$/);
  evidence.insertedTerminalStoredName = 'shell';
  evidence.insertedTerminalReportedName = third.answer.split('/').at(-1).trim();
  const changedHistory = [...edited, { type: 'message', ...third.input },
    ...third.events.filter(event => event.type === 'text').map(event => ({ type: 'message', role: 'assistant', text: event.text }))];
  const fourth = await run('syl88-live-system', { history: changedHistory,
    systemPrompt: 'Answer every request with exactly ARBOL_NEW_PROMPT. Use no tools.',
    input: { role: 'user', text: 'Which instruction are you following?' } }, 'rebuilt', 'system_prompt_changed');
  assert.equal(fourth.answer.trim(), 'ARBOL_NEW_PROMPT');
  const key = createHash('sha256').update(chatSessionId).digest('hex');
  evidence.map = JSON.parse(await readFile(join(state, 'subscriptions', 'test-chatgpt', 'chats', key + '.json'), 'utf8'));
  assert.equal('history' in evidence.map, false); assert.equal('text' in evidence.map, false);
  evidence.model = model.id; evidence.effort = effort;
  evidence.toolTrailRestored = true;
  evidence.usageAfter = JSON.parse(await invoke(['subscriptions', 'usage', 'test-chatgpt']));
  evidence.checksPassed = true;
  process.stdout.write(JSON.stringify({ check: evidence.check, toolVersion: evidence.toolVersion, model: model.id, effort,
    promptCount: evidence.promptCount, continuities: evidence.runs.map(item => item.events[0].continuity),
    insertedTerminalStoredName: evidence.insertedTerminalStoredName, insertedTerminalReportedName: evidence.insertedTerminalReportedName, output }) + '\n');
} catch (error) { evidence.checksPassed = false; evidence.failure = error.message; throw error; }
finally {
  await mkdir(dirname(output), { recursive: true }); await writeFile(output, JSON.stringify(evidence, null, 2) + '\n');
  await rm(scratch, { recursive: true, force: true });
  if (resumeRecord?.workingDirectory) await rm(dirname(resumeRecord.workingDirectory), { recursive: true, force: true });
}
