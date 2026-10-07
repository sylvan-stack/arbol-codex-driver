// No turn/start, prompts, login or account requests: probe local continuity RPCs.
import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdtemp, mkdir, readFile, readdir, realpath, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { setTimeout as wait } from 'node:timers/promises';
import { promisify } from 'node:util';
import { AppServer } from '../dist/src/app-server.js';
import { historyItems } from '../dist/src/history.js';
import { ownerAlive } from '../dist/src/state.js';

if (process.argv.length !== 4) throw new Error('Usage: probe-continuity.mjs <codex-path> <record-path>');
const exec = promisify(execFile);
const toolPath = resolve(process.argv[2]);
const output = resolve(process.argv[3]);
const scratch = await realpath(await mkdtemp(join(tmpdir(), 'syl88-protocol-')));
const home = join(scratch, 'codex');
const cwd = join(scratch, 'work');
await mkdir(home, { mode: 0o700 });
await mkdir(cwd, { mode: 0o700 });
const env = { HOME: scratch, PATH: `${dirname(process.execPath)}:/opt/homebrew/bin:/usr/bin:/bin`, LANG: 'C', TMPDIR: scratch };
const requests = [];
const servers = [];
const safe = value => JSON.parse(JSON.stringify(value).replaceAll(scratch, '<probe-home>'));
const request = async (server, method, params) => {
  assert.ok(['thread/start', 'thread/inject_items', 'thread/read', 'thread/resume'].includes(method));
  const result = await server.request(method, params);
  requests.push({ method, params: safe(params), result: safe(result) });
  return result;
};
const schema = async (directory, name) => {
  const files = await readdir(directory, { recursive: true });
  const file = files.find(path => path === name || path.endsWith('/' + name));
  assert.ok(file, `Generated stable schema contains ${name}`);
  const text = await readFile(join(directory, file), 'utf8');
  return { file, text, value: JSON.parse(text) };
};
const rollout = async (threadId, expectedCalls) => {
  const deadline = Date.now() + 5000;
  while (Date.now() < deadline) {
    const files = await readdir(join(home, 'sessions'), { recursive: true }).catch(error => {
      if (error.code === 'ENOENT') return []; throw error;
    });
    const file = files.find(path => path.endsWith(`-${threadId}.jsonl`));
    if (file) {
      const text = await readFile(join(home, 'sessions', file), 'utf8');
      const lines = text.trim().split('\n').map(line => JSON.parse(line));
      const items = lines.filter(line => line.type === 'response_item').map(line => line.payload);
      if (expectedCalls.every(id => items.some(item => item.type === 'function_call_output' && item.call_id === id))) {
        return { file: safe(file), text, lines, items };
      }
    }
    await wait(50);
  }
  throw new Error('Codex did not write the injected items to its saved rollout within five seconds.');
};
const notifications = async server => {
  const all = server.takeNotifications();
  // Local restoration can queue its notifications just after the RPC answer.
  const deadline = Date.now() + 2000;
  while (Date.now() < deadline) {
    try { all.push(await server.nextNotification({ timeoutMs: 100 })); }
    catch (error) { if (/Timed out waiting for codex output/.test(error.message)) break; throw error; }
  }
  return all.map(({ method, params }) => ({ method, ...(params?.threadId ? { threadId: params.threadId } : {}),
    ...(params?.turnId ? { turnId: params.turnId } : {}),
    ...(params?.turn ? { turn: safe(params.turn) } : {}),
    ...(params?.item ? { item: safe(params.item) } : {}) }));
};

let record;
try {
  const version = await exec(toolPath, ['--version'], { env: { ...env, CODEX_HOME: home }, cwd: scratch, timeout: 30000 });
  const schemaDirectory = join(scratch, 'schema');
  await exec(toolPath, ['app-server', 'generate-json-schema', '--out', schemaDirectory],
    { env: { ...env, CODEX_HOME: home }, cwd: scratch, timeout: 30000 });
  const client = await schema(schemaDirectory, 'ClientRequest.json');
  const methods = client.value.oneOf.flatMap(variant => variant.properties?.method?.enum ?? []);
  const used = ['initialize', 'config/read', 'thread/start', 'thread/inject_items', 'thread/read', 'thread/resume'];
  for (const method of used) assert.ok(methods.includes(method), `${method} must be in the stable request schema`);
  const resume = await schema(schemaDirectory, 'ThreadResumeParams.json');
  const inject = await schema(schemaDirectory, 'ThreadInjectItemsParams.json');
  const read = await schema(schemaDirectory, 'ThreadReadParams.json');
  assert.ok(resume.value.required.includes('threadId'));
  assert.ok('model' in resume.value.properties);
  assert.ok(!('history' in resume.value.properties), 'The unstable resume history field is excluded');
  for (const field of ['threadId', 'items']) {
    assert.ok(field in inject.value.properties); assert.ok(inject.value.required.includes(field));
  }
  assert.ok(read.value.required.includes('threadId')); assert.ok('includeTurns' in read.value.properties);
  const picture = { mediaType: 'image/png',
    data: 'iVBORw0KGgoAAAANSUhEUgAAAGAAAABgCAIAAABt+uBvAAABC0lEQVR4nO3OMQ0AIAAEsfdvGhyw9gaSCuh29r34QZwfxPlBnB/E+UGcH8T5QZwfxPlBnB/E+UGcH8T5QZwfxPlBnB/E+UGcH8T5QZwfxPlBnB/E+UGcH8T5QZwfxPlBnB/E+UGcH8T5QZwfxPlBnB/E+UGcH8T5QZwfxPlBnB/E+UGcH8T5QZwfxPlBnB/E+UGcH8T5QZwfxPlBnB/E+UGcH8T5QZwfxPlBnB/E+UGcH8T5QZwfxPlBnB/E+UGcH8T5QZwfxPlBnB/E+UGcH8T5QZwfxPlBnB/E+UGcH8T5QZwfxPlBnB/E+UGcH8T5QZwfxPlBnB/E+UGcH8T5QZwfxPlBnB/E+UHbBY393g69gixzAAAAAElFTkSuQmCC' };
  const history = [
    { type: 'message', role: 'user', text: 'Synthetic earlier message with one picture.', images: [picture] },
    { type: 'tool_call', name: 'shell', input: { command: 'printf synthetic-ok', cwd }, ok: true,
      result: { output: 'synthetic-ok', exitCode: 0 } },
    { type: 'message', role: 'assistant', text: 'Synthetic complete reply.', images: [picture] },
    { type: 'tool_call', name: 'shell', input: { command: 'printf synthetic-partial; exit 2', cwd }, ok: false,
      result: { output: 'synthetic-partial', exitCode: 2 }, error: 'synthetic failure' },
    { type: 'tool_call', name: 'Bash', input: { command: 'printf cross-driver', description: 'Synthetic other Driver call' },
      ok: true, result: 'cross-driver' },
    { type: 'message', role: 'assistant', text: 'Synthetic final reply.' },
  ];
  const items = historyItems(history);
  const calls = items.filter(item => item.type === 'function_call');
  for (const call of calls) {
    assert.match(call.call_id, /^call_[a-zA-Z0-9]{24}$/);
    assert.equal(items.filter(item => item.type === 'function_call_output' && item.call_id === call.call_id).length, 1);
  }
  let server = await AppServer.start({ toolPath, home, env, cwd }); servers.push(server);
  const handshakeVersion = server.toolVersion;
  const first = await request(server, 'thread/start', { cwd, approvalPolicy: 'never', sandbox: 'read-only', ephemeral: false,
    model: 'gpt-5.6-luna', developerInstructions: 'Synthetic continuity protocol check; no inference is requested.' });
  assert.equal(typeof first.thread?.id, 'string');
  const threadId = first.thread.id;
  assert.deepEqual(await request(server, 'thread/inject_items', { threadId, items }), {});
  const saved = await rollout(threadId, calls.map(call => call.call_id));
  const inserted = saved.items.filter(item => item.type === 'function_call' || item.type === 'function_call_output' ||
    item.type === 'message' && ['user', 'assistant'].includes(item.role) && item.content?.some(part => part.text?.startsWith('Synthetic')));
  assert.equal(inserted.length, items.length);
  for (const [index, actual] of inserted.entries()) {
    const expected = items[index];
    assert.equal(actual.type, expected.type);
    if (expected.type === 'message') {
      assert.equal(actual.role, expected.role); assert.deepEqual(actual.content, expected.content);
    } else if (expected.type === 'function_call') {
      assert.equal(actual.name, expected.name); assert.equal(actual.arguments, expected.arguments); assert.equal(actual.call_id, expected.call_id);
    } else { assert.equal(actual.call_id, expected.call_id); assert.equal(actual.output, expected.output); }
  }
  const before = await request(server, 'thread/read', { threadId, includeTurns: true });
  assert.deepEqual(before.thread?.turns, []);
  const startupBeforeResume = await notifications(server);
  await server.end(); assert.equal(await ownerAlive(server.owner), false);
  server = await AppServer.start({ toolPath, home, env, cwd }); servers.push(server);
  const resumed = await request(server, 'thread/resume', { threadId, model: 'gpt-6-astra' });
  assert.equal(resumed.thread?.id, threadId);
  assert.equal(resumed.model, 'gpt-6-astra');
  const after = await request(server, 'thread/read', { threadId, includeTurns: true });
  assert.deepEqual(after.thread?.turns, []);
  const startupAfterResume = await notifications(server);
  await server.end(); assert.equal(await ownerAlive(server.owner), false);
  record = { check: 'probe.continuity', date: new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Madrid',
    year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date()), node: process.version,
    toolVersion: version.stdout.trim(), handshakeVersion, promptCount: 0, accountRequestCount: 0,
    freshPrivateHome: true, experimentalSchemaIncluded: false, stableRequests: used,
    schema: { clientSha256: createHash('sha256').update(client.text).digest('hex'),
      resume: { file: resume.file, required: resume.value.required, modelOverrideAccepted: true, modelReported: resumed.model },
      inject: { file: inject.file, required: inject.value.required },
      read: { file: read.file, required: read.value.required, includeTurns: true } },
    requests, savedRollout: { file: saved.file, itemTypes: inserted.map(item => item.type), items: safe(inserted),
      pairedCallIds: calls.map(call => call.call_id), nativeCallNames: calls.map(call => call.name),
      successShellOutput: inserted.find(item => item.type === 'function_call_output' && item.call_id === calls[0].call_id).output,
      failedShellOutput: inserted.find(item => item.type === 'function_call_output' && item.call_id === calls[1].call_id).output,
      userImagesAccepted: true, assistantImagesAccepted: true },
    threadRead: { turnsBeforeResume: before.thread.turns, turnsAfterResume: after.thread.turns,
      injectedItemsVisibleAsTurns: false }, startupBeforeResume, startupAfterResume,
    resumedInNewProcess: true, appServersEndedOnInputEof: true, privateHomeRemoved: true };
} finally {
  for (const server of servers) await server.close();
  await rm(scratch, { recursive: true, force: true });
}
await mkdir(dirname(output), { recursive: true });
await writeFile(output, JSON.stringify(record, null, 2) + '\n');
process.stdout.write(JSON.stringify({ check: record.check, toolVersion: record.toolVersion, promptCount: 0,
  nativeCallNames: record.savedRollout.nativeCallNames, assistantImagesAccepted: true,
  resumedInNewProcess: true, injectedItemsVisibleAsTurns: false, output }) + '\n');
