// No prompt or account login: check the installed stable schema and handshake.
import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { AppServer } from '../dist/src/app-server.js';
import { ownerAlive } from '../dist/src/state.js';
const exec = promisify(execFile);
const toolPath = resolve(process.argv[2]);
const output = resolve(process.argv[3]);
const scratch = await mkdtemp(join(tmpdir(), 'syl86-protocol-'));
const home = join(scratch, 'codex'); await mkdir(home);
const env = { HOME: scratch, PATH: `${dirname(process.execPath)}:/opt/homebrew/bin:/usr/bin:/bin`, LANG: 'C', TMPDIR: scratch };
let server;
try {
  const version = await exec(toolPath, ['--version'], { env: { ...env, CODEX_HOME: home }, cwd: scratch });
  const schemaDirectory = join(scratch, 'schema');
  await exec(toolPath, ['app-server', 'generate-json-schema', '--out', schemaDirectory], { env: { ...env, CODEX_HOME: home }, cwd: scratch });
  const clientText = await readFile(join(schemaDirectory, 'ClientRequest.json'), 'utf8');
  const client = JSON.parse(clientText);
  const methods = client.oneOf.flatMap(variant => variant.properties?.method?.enum ?? []);
  const used = ['initialize', 'config/read', 'account/read', 'model/list', 'thread/start', 'turn/start'];
  for (const method of used) assert.ok(methods.includes(method), `${method} must be in the stable request schema`);
  const thread = JSON.parse(await readFile(join(schemaDirectory, 'v2/ThreadStartParams.json'), 'utf8'));
  const turn = JSON.parse(await readFile(join(schemaDirectory, 'v2/TurnStartParams.json'), 'utf8'));
  const threadFields = ['cwd', 'model', 'approvalPolicy', 'sandbox', 'serviceTier', 'developerInstructions', 'ephemeral'];
  const turnFields = ['threadId', 'input', 'model', 'effort', 'summary', 'approvalPolicy', 'sandboxPolicy', 'serviceTier'];
  for (const field of threadFields) assert.ok(field in thread.properties, `Stable thread/start field ${field}`);
  for (const field of turnFields) assert.ok(field in turn.properties, `Stable turn/start field ${field}`);
  const picture = turn.definitions.UserInput.oneOf.find(variant => variant.properties?.type?.enum?.includes('localImage'));
  assert.ok(picture); assert.ok(picture.required.includes('path'));
  server = await AppServer.start({ toolPath, home, env });
  const config = server.effectiveConfig;
  assert.equal(config.web_search, 'live'); assert.equal(config.features.memories, false);
  const handshakeVersion = server.toolVersion;
  await server.end(); assert.equal(await ownerAlive(server.owner), false);
  const record = { check: 'probe.run-protocol', date: new Date().toISOString().slice(0, 10), node: process.version,
    toolVersion: version.stdout.trim(), handshakeVersion, promptCount: 0, experimentalSchemaIncluded: false,
    stableRunRequests: used, stableThreadFields: threadFields, stableTurnFields: turnFields,
    localImage: picture, schemaSha256: createHash('sha256').update(clientText).digest('hex'),
    configurationApplied: { check_for_update_on_startup: config.check_for_update_on_startup, web_search: config.web_search,
      cli_auth_credentials_store: config.cli_auth_credentials_store, analytics: config.analytics, memories: config.features.memories },
    appServerEndedOnInputEof: true, privateHomeRemoved: true };
  await mkdir(dirname(output), { recursive: true }); await writeFile(output, JSON.stringify(record, null, 2) + '\n');
  process.stdout.write(JSON.stringify({ check: record.check, toolVersion: record.toolVersion, promptCount: 0, stableRequests: used, localImageConfirmed: true, output }) + '\n');
} finally { await server?.close(); await rm(scratch, { recursive: true, force: true }); }
