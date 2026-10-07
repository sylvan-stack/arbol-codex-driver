// Opt-in: exactly two short inference requests on the pre-authorized test account.
import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { mkdtemp, mkdir, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
const exec = promisify(execFile);
const toolPath = resolve(process.argv[2]);
const state = resolve(process.argv[3]);
const output = resolve(process.argv[4]);
const cli = resolve(import.meta.dirname, '../bin/arbol-codex-driver.mjs');
const scratch = await mkdtemp(join(tmpdir(), 'syl86-live-'));
const env = { HOME: scratch, PATH: `${dirname(process.execPath)}:/opt/homebrew/bin:/usr/bin:/bin`, LANG: 'C', TMPDIR: scratch };
const evidence = { check: 'live.run', date: new Date().toISOString().slice(0, 10), node: process.version,
  subscription: 'test-chatgpt', accountHomeUsedDirectly: true, environmentNames: Object.keys(env).sort(), promptCount: 2, runs: [] };
try {
  await mkdir(join(scratch, '.arbol'));
  await writeFile(join(scratch, '.arbol', 'arbol-codex-driver.json'), JSON.stringify({ toolPath }), { mode: 0o600 });
  const info = JSON.parse((await exec(process.execPath, [cli, '--state-dir', state, 'info'], { env, timeout: 40000 })).stdout);
  evidence.toolVersion = info.tool.version;
  const accountUsage = async () => JSON.parse((await exec(process.execPath, [cli, '--state-dir', state, 'subscriptions', 'usage', 'test-chatgpt'], { env, timeout: 40000 })).stdout);
  const usageBefore = await accountUsage();
  assert.equal(usageBefore.outcome, 'ok', 'Read quota before spending it.');
  assert.ok(!usageBefore.windows.some(window => window.limitReached || window.usedPercent >= 100), 'Do not run a live check with an exhausted usage window.');
  evidence.usageBefore = usageBefore;
  const models = JSON.parse((await exec(process.execPath, [cli, '--state-dir', state, 'subscriptions', 'models', 'test-chatgpt'], { env, timeout: 40000 })).stdout);
  assert.equal(models.source, 'tool');
  const model = models.models.find(item => item.id === 'gpt-5.6-luna') ?? models.models.find(item => item.id === 'gpt-6-luna');
  assert.ok(model, 'A Luna test model must be available.');
  assert.ok(model.efforts.includes('low'));
  const cwd = join(scratch, 'work'); await mkdir(cwd);
  for (const tools of ['all', 'none']) {
    const id = `syl86-live-${tools}`;
    const request = { runId: id, subscriptionId: 'test-chatgpt', model: model.id, effort: 'low', tools, history: [],
      ...(tools === 'all' ? { workingDirectory: cwd } : {}),
      systemPrompt: 'Answer exactly ARBOL_RUN_OK. Use no tools.', input: { role: 'user', text: 'Reply with ARBOL_RUN_OK.' }, labels: { check: tools === 'all' ? 'live.run' : 'live.no-tools' } };
    const file = join(scratch, `${tools}.json`); await writeFile(file, JSON.stringify(request), { mode: 0o600 });
    const reply = await exec(process.execPath, [cli, '--state-dir', state, 'run', '--request', file], { env, timeout: 90000, maxBuffer: 2 * 1024 * 1024 });
    assert.equal(reply.stderr, '');
    const events = reply.stdout.trim().split('\n').map(line => JSON.parse(line));
    events.forEach((event, index) => { assert.equal(event.seq, index + 1); assert.equal(event.runId, id); assert.deepEqual(event.labels, request.labels); });
    assert.equal(events[0].type, 'started'); assert.equal(events[0].continuity, 'fresh');
    assert.equal(events.filter(event => event.type === 'finished').length, 1);
    assert.equal(events.at(-1).type, 'finished'); assert.equal(events.at(-1).outcome, 'completed');
    assert.equal(events.filter(event => event.type === 'text').map(event => event.text).join('').trim(), 'ARBOL_RUN_OK');
    assert.ok(events.some(event => event.type === 'usage'));
    assert.ok(events.at(-1).usage.inputTokens > 0); assert.ok(events.at(-1).usage.outputTokens > 0);
    assert.equal('costUsd' in events.at(-1).usage, false);
    assert.equal(await readFile(file, 'utf8'), JSON.stringify(request));
    const temporary = join(state, 'tmp', id);
    await assert.rejects(readdir(temporary)); await assert.rejects(readFile(join(state, 'runs', id + '.json')));
    evidence.runs.push({ check: request.labels.check, tools, model: model.id, effort: 'low', events,
      temporaryFolderRemoved: true, activeRunRecordRemoved: true, requestUnchanged: true });
  }
  assert.deepEqual(JSON.parse((await exec(process.execPath, [cli, '--state-dir', state, 'runs', 'list'], { env, timeout: 10000 })).stdout), []);
  evidence.usageAfter = await accountUsage();
  evidence.runTokensSpent = evidence.runs.map(item => item.events.at(-1).usage);
  evidence.checksPassed = true;
  await mkdir(dirname(output), { recursive: true }); await writeFile(output, JSON.stringify(evidence, null, 2) + '\n');
  process.stdout.write(JSON.stringify({ check: 'live.run', toolVersion: evidence.toolVersion, promptCount: 2, model: model.id,
    outcomes: evidence.runs.map(item => item.events.at(-1).outcome), usageReported: true, temporaryFoldersRemoved: true, output }) + '\n');
} finally { await rm(scratch, { recursive: true, force: true }); }
