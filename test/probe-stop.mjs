// No prompts, no account access: stable stopping schema, an idle-thread
// interrupt bounded by the caller, transport usability afterwards and EOF exit.
import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdtemp, mkdir, readFile, readdir, realpath, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { promisify } from 'node:util';
import { AppServer } from '../dist/src/app-server.js';
import { ownerAlive } from '../dist/src/state.js';
if (process.argv.length !== 4) throw new Error('Usage: probe-stop.mjs <codex-path> <record-path>');
const exec = promisify(execFile);
const toolPath = resolve(process.argv[2]);
const output = resolve(process.argv[3]);
const scratch = await realpath(await mkdtemp(join(tmpdir(), 'syl89-protocol-')));
const home = join(scratch, 'codex'); const cwd = join(scratch, 'work');
await mkdir(home, { mode: 0o700 }); await mkdir(cwd, { mode: 0o700 });
const env = { HOME: scratch, PATH: `${dirname(process.execPath)}:/opt/homebrew/bin:/usr/bin:/bin`, LANG: 'C', TMPDIR: scratch };
const safe = value => JSON.parse(JSON.stringify(value).replaceAll(scratch, '<probe-home>'));
const record = { check: 'probe.stopping', date: new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Madrid',
  year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date()), node: process.version,
  promptCount: 0, accountRequestCount: 0, freshPrivateHome: true, experimentalSchemaIncluded: false, requests: [] };
let server;
try {
  record.toolVersion = (await exec(toolPath, ['--version'], { env: { ...env, CODEX_HOME: home }, cwd: scratch, timeout: 30000 })).stdout.trim();
  const schemaDirectory = join(scratch, 'schema');
  await exec(toolPath, ['app-server', 'generate-json-schema', '--out', schemaDirectory], { env: { ...env, CODEX_HOME: home }, cwd: scratch, timeout: 30000 });
  const files = await readdir(schemaDirectory, { recursive: true });
  const schema = async name => {
    const file = files.find(path => path === name || path.endsWith('/' + name)); assert.ok(file, `Stable schema contains ${name}.`);
    const raw = await readFile(join(schemaDirectory, file), 'utf8'); return { file, raw, value: JSON.parse(raw) };
  };
  const client = await schema('ClientRequest.json');
  const methods = client.value.oneOf.flatMap(variant => variant.properties?.method?.enum ?? []);
  for (const method of ['initialize', 'config/read', 'thread/start', 'thread/read', 'turn/interrupt']) assert.ok(methods.includes(method), `${method} is stable.`);
  const interrupt = await schema('TurnInterruptParams.json');
  assert.deepEqual(interrupt.value.required.slice().sort(), ['threadId', 'turnId']);
  for (const field of ['threadId', 'turnId']) assert.equal(interrupt.value.properties[field].type, 'string');
  const started = await schema('TurnStartedNotification.json');
  const completed = await schema('TurnCompletedNotification.json');
  for (const item of [started, completed]) {
    for (const field of ['threadId', 'turn']) assert.ok(item.value.required.includes(field));
  }
  const item = await schema('ItemStartedNotification.json');
  const hasActivity = item.raw.includes('subAgentActivity') && item.raw.includes('agentThreadId');
  assert.ok(hasActivity, 'Stable items describe sub-agent activity and its thread.');
  const hasCollaborationSpawn = item.raw.includes('spawnAgent') && item.raw.includes('receiverThreadIds');
  assert.ok(hasCollaborationSpawn, 'Stable items also describe collaboration spawning and receiver threads.');
  record.schema = { clientSha256: createHash('sha256').update(client.raw).digest('hex'),
    interrupt: { file: interrupt.file, required: interrupt.value.required },
    turnStarted: { file: started.file, required: started.value.required },
    turnCompleted: { file: completed.file, required: completed.value.required },
    subAgentActivity: { file: item.file, hasAgentThreadId: hasActivity },
    collaborationSpawn: { file: item.file, hasSpawnAgentAndReceiverThreadIds: hasCollaborationSpawn } };
  server = await AppServer.start({ toolPath, home, env, cwd }); record.handshakeVersion = server.toolVersion;
  const request = async (method, params) => {
    assert.ok(['thread/start', 'thread/read'].includes(method));
    const result = await server.request(method, params); record.requests.push({ method, params: safe(params), result: safe(result) }); return result;
  };
  const thread = await request('thread/start', { cwd, approvalPolicy: 'never', sandbox: 'read-only', ephemeral: false,
    developerInstructions: 'Synthetic stopping protocol check; no inference is requested.' });
  assert.equal(typeof thread.thread?.id, 'string'); const threadId = thread.thread.id;
  const before = await request('thread/read', { threadId, includeTurns: false }); assert.deepEqual(before.thread?.turns, []);
  const start = performance.now();
  let interruptResult;
  try { interruptResult = { result: await server.request('turn/interrupt', { threadId, turnId: 'idle-probe-turn' }, { signal: AbortSignal.timeout(250) }) }; }
  catch (error) { interruptResult = { error: safe(error.result ?? { message: error.message }) }; }
  record.idleInterrupt = { params: { threadId, turnId: 'idle-probe-turn' }, elapsedMs: Math.round(performance.now() - start), ...interruptResult };
  assert.ok(record.idleInterrupt.elapsedMs < 2000, 'An unanswered idle interrupt is bounded by the caller.');
  const after = await request('thread/read', { threadId, includeTurns: false }); assert.deepEqual(after.thread?.turns, []);
  record.transportUsableAfterAbandonedInterrupt = true;
  const ended = performance.now(); await server.end();
  record.eofCleanupElapsedMs = Math.round(performance.now() - ended); assert.ok(record.eofCleanupElapsedMs < 5000);
  assert.equal(await ownerAlive(server.owner), false); record.appServerEnded = true;
  record.checksPassed = true;
} catch (error) { record.checksPassed = false; record.failure = error.message; throw error; }
finally {
  await server?.close(); await rm(scratch, { recursive: true, force: true }); record.privateHomeRemoved = true;
  await mkdir(dirname(output), { recursive: true }); await writeFile(output, JSON.stringify(record, null, 2) + '\n');
}
process.stdout.write(JSON.stringify({ check: record.check, toolVersion: record.toolVersion, promptCount: 0,
  idleInterruptElapsedMs: record.idleInterrupt.elapsedMs, appServerEnded: true, output }) + '\n');
