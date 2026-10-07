// One no-quota probe, intentionally separate from the automatic unit tests.
import { mkdtemp, mkdir, writeFile, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, dirname, resolve } from 'node:path';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
const exec = promisify(execFile);
const tool = resolve(process.argv[2]);
const output = resolve(process.argv[3]);
const home = await mkdtemp(join(tmpdir(), 'syl79-real-info-'));
try {
  await mkdir(join(home, '.arbol'), { mode: 0o700 });
  await writeFile(join(home, '.arbol', 'arbol-codex-driver.json'), JSON.stringify({ toolPath: tool }), { mode: 0o600 });
  const cli = resolve(import.meta.dirname, '../bin/arbol-codex-driver.mjs');
  const env = { HOME: home, PATH: `${dirname(process.execPath)}:/usr/bin:/bin`, LANG: 'C', TMPDIR: home };
  const result = await exec(process.execPath, [cli, 'info'], { env, cwd: home, timeout: 20000 });
  const info = JSON.parse(result.stdout);
  if (!info.tool.supported) throw new Error('Installed codex is unsupported.');
  const cache = JSON.parse(await readFile(join(info.stateDirectory, 'tool.json'), 'utf8'));
  const record = {
    check: 'probe.base-info', date: new Date().toISOString().slice(0, 10), platform: process.platform,
    node: process.version, tool: info.tool, versionLine: `codex-cli ${cache.version}`,
    environmentNames: Object.keys(env).sort(), temporaryHome: true, promptCount: 0,
    result: { ...info, stateDirectory: '<probe-home>/Library/Application Support/Arbol/drivers/codex', settingsFile: '<probe-home>/.arbol/arbol-codex-driver.json' },
  };
  await mkdir(dirname(output), { recursive: true });
  await writeFile(output, JSON.stringify(record, null, 2) + '\n');
  process.stdout.write(JSON.stringify(record, null, 2) + '\n');
} finally { await rm(home, { recursive: true, force: true }); }
