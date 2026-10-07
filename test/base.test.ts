import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile, writeFile, mkdir, stat, readdir, copyFile, utimes, realpath } from 'node:fs/promises';
import { join } from 'node:path';
import { parseArguments } from '../src/arguments.js';
import { buildIdentity } from '../src/build.js';
import { Failure, errorCodes, safeFailure, safeText } from '../src/errors.js';
import { cleanEnvironment } from '../src/environment.js';
import { readSettings } from '../src/settings.js';
import { State } from '../src/state.js';
import { supportedVersion } from '../src/tool.js';
import { fixture, invoke, received } from './helpers.js';

test('base.info reports package, Build, contract, settings and supported tool', async t => {
  const f = await fixture(t);
  const { root } = await import('./helpers.js');
  const record = await readFile(join(root, 'build.json'), 'utf8').then(text => JSON.parse(text)).catch(error => {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return undefined;
    throw error;
  });
  const pkg = JSON.parse(await readFile(join(root, 'package.json'), 'utf8'));
  const result = await invoke(['--state-dir', f.state, 'info'], f.env);
  assert.equal(result.code, 0);
  assert.deepEqual(result.result, { driver: 'codex', version: record?.packageVersion ?? pkg.version, build: record?.build ?? '0', contract: 1, stateDirectory: f.state,
    settingsFile: join(f.home, '.arbol', 'arbol-codex-driver.json'), tool: { name: 'codex', path: join(f.tool, 'codex'), version: '0.159.2', supported: true, oldestSupported: '0.159.2' } });
  assert.equal(result.stderr, '');
  assert.equal(await readFile(join(f.state, 'format'), 'utf8'), '1\n');
  assert.equal((await stat(f.state)).mode & 0o777, 0o700);
  assert.equal((await stat(join(f.state, 'format'))).mode & 0o777, 0o600);
  assert.equal((await stat(join(f.state, 'tool.json'))).mode & 0o777, 0o600);
  assert.deepEqual(await readdir(join(f.state, 'tmp')), []);
});

test('base.tool-cache reuses the version and asks after size, mtime or path changes', async t => {
  const f = await fixture(t);
  const args = ['info', `--state-dir=${f.state}`];
  await invoke(args, f.env); await invoke(args, f.env);
  assert.equal((await received(f.tool)).length, 1);
  const tool = join(f.tool, 'codex');
  await writeFile(tool, await readFile(tool, 'utf8') + '# changed size\n', { mode: 0o700 });
  await invoke(args, f.env);
  assert.equal((await received(f.tool)).length, 2);
  const later = new Date(Date.now() + 5000);
  await utimes(tool, later, later);
  await invoke(args, f.env);
  assert.equal((await received(f.tool)).length, 3);
  await copyFile(tool, join(f.tool, 'new-codex'));
  await writeFile(join(f.home, '.arbol', 'arbol-codex-driver.json'), JSON.stringify({ toolPath: join(f.tool, 'new-codex') }));
  await invoke(args, f.env);
  assert.equal((await received(f.tool)).length, 4);
});

test('base.tool-missing keeps info usable and refuses an operation needing codex', async t => {
  const f = await fixture(t);
  await writeFile(join(f.home, '.arbol', 'arbol-codex-driver.json'), JSON.stringify({ toolPath: join(f.home, 'absent') }));
  const info = await invoke(['info', '--state-dir', f.state], f.env);
  assert.equal(info.code, 0); assert.equal(info.result.tool.supported, false); assert.equal(info.result.tool.path, undefined);
  const run = await invoke(['dev', 'probe', '--state-dir', f.state], f.env);
  assert.equal(run.code, 1); assert.equal(run.result.error.code, 'tool_missing');
  assert.match(run.result.error.message, /codex.*not found.*0\.159\.2/);
  assert.equal(run.result.error.detail.neededVersion, '0.159.2');
});

test('base.tool-old reports both versions and does not start a run', async t => {
  const f = await fixture(t);
  await writeFile(join(f.tool, 'scenario'), 'C31 old\n');
  const info = await invoke(['info', '--state-dir', f.state], f.env);
  assert.equal(info.result.tool.supported, false); assert.equal(info.result.tool.version, '0.159.1');
  const result = await invoke(['dev', 'probe', '--state-dir', f.state], f.env);
  assert.equal(result.code, 1); assert.equal(result.result.error.code, 'tool_unsupported');
  assert.equal(result.result.error.detail.toolVersion, '0.159.1');
  assert.match(result.result.error.message, /0\.159\.1.*0\.159\.2/);
  assert.deepEqual((await received(f.tool)).map(r => r.arguments), [['--version']]);
  for (const version of ['0.159.2', '0.160.0', '1.0.0', '12.0.0']) assert.equal(supportedVersion(version), true);
  for (const version of ['0.159.1', '0.158.999', 'garbage', '0.159.2-beta']) assert.equal(supportedVersion(version), false);
});

test('base.environment discards inherited account and runtime variables', async t => {
  const f = await fixture(t);
  const env = { ...f.env, ANTHROPIC_API_KEY: 'secret-sentinel', CLAUDECODE: '1', CLAUDE_CODE_OAUTH_TOKEN: 'secret-sentinel',
    OPENAI_API_KEY: 'secret-sentinel', CODEX_HOME: '/wrong', NODE_OPTIONS: '--invalid-flag', ARBOL_TEST_TIME_SCALE: '2' };
  const result = await invoke(['info', '--state-dir', f.state], { ...env, NODE_OPTIONS: '' });
  assert.equal(result.code, 0);
  const record = (await received(f.tool))[0];
  for (const key of ['ANTHROPIC_API_KEY', 'CLAUDECODE', 'CLAUDE_CODE_OAUTH_TOKEN', 'OPENAI_API_KEY', 'NODE_OPTIONS', 'ARBOL_TEST_TIME_SCALE']) assert.ok(!record.environment.includes(key));
  assert.ok(record.environment.includes('CODEX_HOME'));
  assert.equal(JSON.stringify(record).includes('secret-sentinel'), false);
  assert.deepEqual(cleanEnvironment(env, '/isolated', '/isolated/config'), { PATH: f.env.PATH, LANG: 'C', TMPDIR: f.home, HOME: '/isolated', CODEX_HOME: '/isolated/config' });
});

test('base.settings reloads each invocation, ignores unknown keys and never rewrites the file', async t => {
  const f = await fixture(t);
  const path = join(f.home, '.arbol', 'arbol-codex-driver.json');
  const settings = { toolPath: join(f.tool, 'codex'), future: true, subscriptions: { chatgpt: { defaultModel: 'fixture-model', futureOption: 1 } } };
  const text = JSON.stringify(settings, null, 2);
  await writeFile(path, text);
  const first = await invoke(['info', '--state-dir', f.state], f.env);
  assert.equal(first.code, 0); assert.equal(first.result.notices.length, 2);
  assert.match(first.result.notices[0].message, /future/);
  assert.equal(await readFile(path, 'utf8'), text);
  await writeFile(path, 'broken secret-sentinel');
  const second = await invoke(['info', '--state-dir', f.state], f.env);
  assert.equal(second.code, 1); assert.equal(second.result.error.code, 'invalid_input');
  assert.match(second.result.error.message, /arbol-codex-driver\.json.*JSON/);
  assert.equal(second.stdout.includes('secret-sentinel'), false);
  assert.equal(second.stderr, '');
});

test('base.build-identity reads its own record independently of cwd and environment', async t => {
  const f = await fixture(t);
  const dir = join(f.home, 'build'); await mkdir(join(dir, 'dist', 'src'), { recursive: true });
  await writeFile(join(dir, 'package.json'), JSON.stringify({ name: '@sylvan-stack/arbol-codex-driver', version: '1.0.0' }));
  assert.deepEqual(await buildIdentity(join(dir, 'dist', 'src')), { version: '1.0.0', build: '0' });
  await writeFile(join(dir, 'build.json'), JSON.stringify({ component: 'arbol-codex-driver', build: 'a3', packageVersion: '1.2.3' }));
  assert.deepEqual(await buildIdentity(join(dir, 'dist', 'src')), { version: '1.2.3', build: 'a3' });
  await writeFile(join(dir, 'build.json'), 'broken');
  await assert.rejects(buildIdentity(join(dir, 'dist', 'src')), /Build record/);
});

test('base.state-newer refuses without changing files or permissions', async t => {
  const f = await fixture(t);
  await mkdir(f.state, { mode: 0o755 });
  await writeFile(join(f.state, 'format'), '2\n', { mode: 0o644 });
  const result = await invoke(['info', '--state-dir', f.state], f.env);
  assert.equal(result.code, 1); assert.equal(result.result.error.code, 'state_newer');
  assert.match(result.result.error.message, /2.*1/);
  assert.equal((await stat(f.state)).mode & 0o777, 0o755);
  assert.deepEqual(await readdir(f.state), ['format']);
  assert.equal(await readFile(join(f.state, 'format'), 'utf8'), '2\n');
  await writeFile(join(f.state, 'format'), 'broken secret-sentinel');
  assert.equal((await invoke(['info', '--state-dir', f.state], f.env)).result.error.code, 'internal');
  const state = new State(join(f.home, 'empty'));
  await Promise.all([state.initialize(), state.initialize()]);
  assert.equal(await readFile(join(state.directory, 'format'), 'utf8'), '1\n');
});

test('base.packaged-info reads the running Build record through the executable', async t => {
  const f = await fixture(t);
  const { cp } = await import('node:fs/promises');
  const { execFile } = await import('node:child_process');
  const { promisify } = await import('node:util');
  const { root } = await import('./helpers.js');
  const build = join(f.home, 'build');
  await mkdir(build);
  await cp(join(root, 'bin'), join(build, 'bin'), { recursive: true });
  await cp(join(root, 'dist', 'src'), join(build, 'dist', 'src'), { recursive: true });
  await copyFile(join(root, 'package.json'), join(build, 'package.json'));
  await writeFile(join(build, 'build.json'), JSON.stringify({ component: 'arbol-codex-driver', build: 'a3', packageVersion: '1.2.3' }));
  const result = await promisify(execFile)(process.execPath, [join(build, 'bin', 'arbol-codex-driver.mjs'), 'info', '--state-dir', f.state], { env: { ...f.env, ARBOL_BUILD_NUMBER: 'ff', ARBOL_BUILD_DIR: '/wrong' }, cwd: f.home });
  const info = JSON.parse(result.stdout);
  assert.equal(info.version, '1.2.3'); assert.equal(info.build, 'a3');
});

test('base.stand-in selects C31 and C32 parts and records arguments, environment names and cwd', async t => {
  const f = await fixture(t);
  const { execFile } = await import('node:child_process'); const { promisify } = await import('node:util');
  const { cli } = await import('./helpers.js');
  const result = await promisify(execFile)(process.execPath, [cli, 'dev', 'stand-in', f.tool, '--', '--version'], { env: f.env, cwd: f.home });
  assert.equal(result.stdout, 'codex-cli 0.159.2\n');
  const record = (await received(f.tool))[0];
  assert.equal(record.scenario, 'C31'); assert.equal(record.part, 'supported');
  assert.deepEqual(record.arguments, ['--version']); assert.equal(record.workingDirectory, await realpath(f.home));
  assert.ok(record.environment.includes('HOME')); assert.ok(!JSON.stringify(record).includes(`"HOME":"${f.home}"`));
  await writeFile(join(f.tool, 'scenario'), 'C32 info');
  const info = await promisify(execFile)(process.execPath, [cli, 'dev', 'stand-in', f.tool, '--', '--version'], { env: f.env, cwd: f.home });
  assert.equal(info.stdout, 'codex-cli 0.159.2\n');
  const infoRecord = (await received(f.tool))[1];
  assert.equal(infoRecord.scenario, 'C32'); assert.equal(infoRecord.part, 'info');
  assert.deepEqual(infoRecord.arguments, ['--version']);
  await writeFile(join(f.tool, 'scenario'), 'C31 missing');
  await assert.rejects(promisify(execFile)(process.execPath, [cli, 'dev', 'stand-in', f.tool, '--', '--version'], { env: f.env }), (error: unknown) => (error as { code: number }).code === 127);
});

test('base.cancel exits with 2 and removes its version-probe child and temporary home', async t => {
  const f = await fixture(t);
  const { spawn } = await import('node:child_process');
  const { cli, quote } = await import('./helpers.js');
  const { ownerAlive } = await import('../src/state.js');
  const marker = join(f.home, 'probe-pid');
  const code = `process.on('SIGTERM', () => {}); require('node:fs').writeFileSync(${JSON.stringify(marker)}, String(process.pid)); setInterval(() => {}, 1000);`;
  await writeFile(join(f.tool, 'codex'), `#!/bin/sh\nexec ${quote(process.execPath)} -e ${quote(code)}\n`, { mode: 0o700 });
  const child = spawn(process.execPath, [cli, 'info', '--state-dir', f.state], { env: f.env, stdio: ['ignore', 'pipe', 'pipe'] });
  t.after(() => { child.kill('SIGKILL'); });
  const exit = new Promise<number | null>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('Cancelling an uncooperative probe must finish.')), 3000);
    child.once('close', code => { clearTimeout(timer); resolve(code); });
  });
  for (let i = 0; i < 200; i++) {
    try { await stat(marker); break; } catch { await new Promise<void>(resolve => setTimeout(resolve, 10)); }
  }
  const pid = Number(await readFile(marker, 'utf8'));
  child.kill('SIGTERM');
  assert.equal(await exit, 2);
  assert.equal(await ownerAlive({ pid, startedAt: new Date().toISOString() }), false);
  assert.deepEqual(await readdir(join(f.state, 'tmp')), []);
});


test('base.info finds codex on PATH without a settings file and uses the default state directory', async t => {
  const f = await fixture(t);
  const { unlink } = await import('node:fs/promises');
  await unlink(join(f.home, '.arbol', 'arbol-codex-driver.json'));
  const result = await invoke(['info'], { ...f.env, PATH: `${f.tool}:${f.env.PATH}` });
  assert.equal(result.code, 0);
  assert.equal(result.result.tool.path, join(f.tool, 'codex'));
  assert.equal(result.result.tool.supported, true);
  assert.equal(result.result.stateDirectory, join(f.home, 'Library', 'Application Support', 'Arbol', 'drivers', 'codex'));
  await assert.rejects(stat(join(f.home, '.arbol', 'arbol-codex-driver.json')));
});

test('base.cli returns one typed refusal without echoing caller secrets', async t => {
  const f = await fixture(t);
  for (const args of [[], ['unknown'], ['constructor'], ['toString'], ['__proto__'], ['info', '--unknown'], ['info', '--secret=secret-sentinel'], ['info', '--state-dir'], ['info', 'extra'], ['run', '--tools', 'some'], ['info', '-v', '1']]) {
    const result = await invoke(args, f.env);
    assert.equal(result.code, 1);
    if (args[0] === 'run') {
      assert.equal(result.result.type, 'finished'); assert.equal(result.result.outcome, 'failed'); assert.equal(result.result.seq, 1);
    } else assert.deepEqual(Object.keys(result.result), ['error']);
    assert.equal(result.result.error.code, 'invalid_input');
    assert.equal(result.stdout.includes('secret-sentinel'), false);
    assert.equal(result.stderr, '');
  }
  const later = await invoke(['subscriptions', 'import', 'chatgpt', '--from', 'vendor'], f.env);
  assert.equal(later.code, 1);
  assert.equal(later.result.error.code, 'unsupported');
});

test('base.tool-failure protects tool output and cleans its temporary home', async t => {
  const f = await fixture(t);
  for (const body of ["echo secret-sentinel; exit 1", "echo secret-sentinel", "echo 'codex-cli 0.159.2 extra'"]) {
    await writeFile(join(f.tool, 'codex'), '#!/bin/sh\n' + body + '\n', { mode: 0o700 });
    const result = await invoke(['info', '--state-dir', f.state], f.env);
    assert.equal(result.code, 1);
    assert.equal(result.result.error.code, 'tool_failed');
    assert.equal(result.stdout.includes('secret-sentinel'), false);
    assert.equal(result.stderr, '');
    assert.deepEqual(await readdir(join(f.state, 'tmp')), []);
  }
});

test('base.stand-in-handshake plays the recorded initialize response without Driver state', async t => {
  const f = await fixture(t);
  const { spawn } = await import('node:child_process');
  const { cli } = await import('./helpers.js');
  // A stand-in must still start when the Driver settings themselves are invalid.
  await writeFile(join(f.home, '.arbol', 'arbol-codex-driver.json'), 'invalid');
  const child = spawn(process.execPath, [cli, 'dev', 'stand-in', f.tool, '--', 'app-server'], {
    env: { ...f.env, CODEX_HOME: join(f.home, 'codex-home') }, cwd: f.home, stdio: ['pipe', 'pipe', 'pipe'],
  });
  t.after(() => child.kill('SIGKILL'));
  let stdout = '', stderr = '';
  child.stdout.on('data', chunk => { stdout += chunk; });
  child.stderr.on('data', chunk => { stderr += chunk; });
  const done = new Promise<number | null>((resolve, reject) => { child.once('error', reject); child.once('close', resolve); });
  child.stdin.end(JSON.stringify({ id: 'probe', method: 'initialize', params: { clientInfo: { name: 'arbol-codex-driver', version: '1.0.0' } } }) + '\n');
  assert.equal(await done, 0);
  const response = JSON.parse(stdout);
  assert.equal(response.id, 'probe');
  assert.match(response.result.userAgent, /arbol-codex-driver\/0\.159\.2/);
  assert.equal(response.result.codexHome, join(f.home, 'codex-home'));
  assert.equal(response.result.platformFamily, 'unix');
  assert.equal(stderr, '');
  await assert.rejects(stat(f.state));
  assert.deepEqual((await received(f.tool))[0].arguments, ['app-server']);
});

test('base.tool-descendants removes a wrapper child that keeps the output pipe open', async t => {
  const f = await fixture(t);
  const { quote } = await import('./helpers.js');
  const { processOwner } = await import('../src/state.js');
  const marker = join(f.home, 'descendant-pid');
  const code = `const child = require('node:child_process').spawn(process.execPath, ['-e', 'process.on("SIGTERM", () => {}); setInterval(() => {}, 1000);'], { stdio: ['ignore', process.stdout, 'ignore'] }); require('node:fs').writeFileSync(${JSON.stringify(marker)}, String(child.pid)); console.log('codex-cli 0.159.2'); process.exit(0);`;
  await writeFile(join(f.tool, 'codex'), `#!/bin/sh\nexec ${quote(process.execPath)} -e ${quote(code)}\n`, { mode: 0o700 });
  const result = await invoke(['info', '--state-dir', f.state], f.env);
  const pid = Number(await readFile(marker, 'utf8'));
  t.after(() => { try { process.kill(pid, 'SIGKILL'); } catch { /* Already ended. */ } });
  assert.equal(result.code, 0);
  for (let i = 0; i < 100 && await processOwner(pid); i++) await new Promise<void>(resolve => setTimeout(resolve, 10));
  assert.equal(await processOwner(pid), undefined);
  assert.deepEqual(await readdir(join(f.state, 'tmp')), []);
});
