// No prompt is sent. This deliberately stays outside the automatic suite.
import assert from 'node:assert/strict';
import { execFile, spawn } from 'node:child_process';
import { promisify } from 'node:util';
import { mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { AppServer, DRIVER_CONFIG } from '../dist/src/app-server.js';
import { normalizeAccount, normalizeUsage, readModelCatalog } from '../dist/src/catalog.js';
import { State, ownerAlive, writeJson } from '../dist/src/state.js';
import { Subscriptions } from '../dist/src/subscriptions.js';
const exec = promisify(execFile);
const toolPath = resolve(process.argv[2]);
const testHome = resolve(process.argv[3]);
const output = resolve(process.argv[4]);
const cli = resolve(import.meta.dirname, '../bin/arbol-codex-driver.mjs');
const scratch = await mkdtemp(join(tmpdir(), 'syl81-probe-'));
const env = { HOME: scratch, PATH: `${dirname(process.execPath)}:/opt/homebrew/bin:/usr/bin:/bin`, LANG: 'C', TMPDIR: scratch };
const servers = [];
const record = { check: 'probe.subscriptions', date: new Date().toISOString().slice(0, 10), node: process.version,
  environmentNames: Object.keys(env).sort(), promptCount: 0, fresh: {}, live: {} };
async function start(home) {
  const server = await AppServer.start({ toolPath, home, env }); servers.push(server); return server;
}
function address(value) {
  const url = new URL(value); assert.equal(url.hostname, 'auth.openai.com');
  return { host: url.hostname, pathname: url.pathname };
}
try {
  const version = await exec(toolPath, ['--version'], { env: { ...env, CODEX_HOME: join(scratch, 'version') }, cwd: scratch });
  record.toolVersion = version.stdout.trim();
  const first = await start(join(scratch, 'fresh-one'));
  assert.equal(await readFile(join(scratch, 'fresh-one', 'config.toml'), 'utf8'), DRIVER_CONFIG);
  const config = await first.request('config/read', {});
  record.fresh.config = { check_for_update_on_startup: config.config.check_for_update_on_startup,
    web_search: config.config.web_search, cli_auth_credentials_store: config.config.cli_auth_credentials_store,
    analytics: config.config.analytics, memories: config.config.features.memories };
  assert.equal(normalizeAccount(await first.request('account/read', { refreshToken: false })), undefined);
  const login = await first.request('account/login/start', { type: 'chatgpt' });
  record.fresh.localLogin = address(login.authUrl);
  const second = await start(join(scratch, 'fresh-two'));
  const newer = await second.request('account/login/start', { type: 'chatgpt' });
  record.fresh.secondLocalLogin = address(newer.authUrl);
  const displaced = await first.waitForNotification('account/login/completed', value => value.loginId === login.loginId, { timeoutMs: 10000 });
  assert.equal(displaced.success, false); record.fresh.displaced = { success: displaced.success, error: displaced.error };
  record.fresh.cancel = await second.request('account/login/cancel', { loginId: newer.loginId });
  const device = await second.request('account/login/start', { type: 'chatgptDeviceCode' });
  assert.equal(typeof device.userCode, 'string'); assert.ok(device.userCode.length > 0);
  record.fresh.deviceLogin = { ...address(device.verificationUrl), userCodeReturned: true };
  await second.request('account/login/cancel', { loginId: device.loginId });
  await second.request('account/logout', {});
  assert.equal(normalizeAccount(await second.request('account/read', { refreshToken: false })), undefined);
  record.fresh.logout = 'account cleared';
  await first.close(); await second.close();
  // An account app-server has no inference children. Verify that losing the
  // caller's input pipe ends the real process even without a Driver finalizer.
  const eofHome = join(scratch, 'eof'); await mkdir(eofHome);
  const eof = spawn(toolPath, ['app-server'], { env: { ...env, CODEX_HOME: eofHome }, cwd: scratch, detached: true, stdio: 'pipe' });
  const exited = new Promise(resolve => eof.once('close', code => resolve(code)));
  eof.stdout.resume(); eof.stderr.resume(); eof.stdin.end();
  let eofTimer;
  try {
    const code = await Promise.race([exited, new Promise(resolve => { eofTimer = setTimeout(() => resolve('timeout'), 5000); })]);
    assert.equal(code, 0); record.fresh.callerEofEndsAppServer = true;
  } finally {
    clearTimeout(eofTimer);
    try { process.kill(-eof.pid, 'SIGKILL'); } catch (error) { if (error.code !== 'ESRCH') throw error; }
  }
  // The pre-authorized test account's own home is used directly. No credential
  // file is read, copied, or imported; Codex alone opens its login store.
  const live = await start(testHome);
  const account = normalizeAccount(await live.request('account/read', { refreshToken: true }));
  assert.ok(account);
  const usage = normalizeUsage(await live.request('account/rateLimits/read', {}), account.plan);
  const models = await readModelCatalog(live);
  assert.equal(usage.outcome, 'ok'); assert.equal(models.source, 'tool'); assert.ok(models.models.length);
  await live.close();
  const state = new State(resolve(testHome, '../../..')); await state.initialize();
  const subscriptions = new Subscriptions(state, {}, [], '<probe-settings>', env);
  let local;
  try { local = await subscriptions.record('test-chatgpt'); }
  catch (error) {
    if (error.result?.code !== 'not_found') throw error;
    await subscriptions.create('chatgpt', 'Test ChatGPT', 'test-chatgpt'); local = await subscriptions.record('test-chatgpt');
  }
  const checkedAt = new Date().toISOString();
  const seeded = { ...local, state: 'signed_in', account, checkedAt, updatedAt: checkedAt };
  delete seeded.problem;
  await writeJson(join(state.subscription('test-chatgpt'), 'record.json'), seeded);
  await mkdir(join(scratch, '.arbol'), { mode: 0o700 });
  await writeFile(join(scratch, '.arbol', 'arbol-codex-driver.json'), JSON.stringify({ toolPath }), { mode: 0o600 });
  const replies = {};
  for (const command of ['check', 'usage', 'models']) {
    const response = await exec(process.execPath, [cli, 'subscriptions', command, 'test-chatgpt', '--state-dir', state.directory], { env, cwd: scratch, timeout: 40000 });
    assert.equal(response.stderr, ''); replies[command] = JSON.parse(response.stdout);
  }
  assert.equal(replies.check.state, 'signed_in'); assert.equal(replies.usage.outcome, 'ok'); assert.equal(replies.models.source, 'tool');
  record.live = { check: 'live.subscriptions', subscription: 'test-chatgpt', state: replies.check.state,
    plan: replies.check.account.plan, usage: replies.usage, models: replies.models,
    accountEmailOmitted: true, accountHomeUsedDirectly: true, signOutSkippedToRetainTestLogin: true,
    browserCompletion: 'Previously observed 6 October 2026; no new browser consent performed.' };
  for (const server of servers) { await server.close(); assert.equal(await ownerAlive(server.owner), false); }
  record.noChildProcessesLeft = true;
  await mkdir(dirname(output), { recursive: true }); await writeFile(output, JSON.stringify(record, null, 2) + '\n');
  process.stdout.write(JSON.stringify({ check: record.check, toolVersion: record.toolVersion, promptCount: 0,
    configurationAccepted: true, localLoginAddressReturned: true, deviceCodeReturned: true,
    localReplacementObserved: true, liveAccountState: record.live.state, usageOutcome: record.live.usage.outcome,
    modelCount: record.live.models.models.length, noChildProcessesLeft: true, output }) + '\n');
} finally {
  for (const server of servers) await server.close();
  await rm(scratch, { recursive: true, force: true });
}
