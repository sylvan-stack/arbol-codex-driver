import { mkdtemp, mkdir, writeFile, rm, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, dirname, resolve } from 'node:path';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import type { TestContext } from 'node:test';
import type { ProcessEnv } from '../src/types.js';
const exec = promisify(execFile);
export const root = resolve(import.meta.dirname, '../..');
export const cli = join(root, 'bin', 'arbol-codex-driver.mjs');
export const quote = (text: string): string => "'" + text.replaceAll("'", "'\\''") + "'";
export async function fixture(t: TestContext): Promise<{ home: string; tool: string; state: string; env: ProcessEnv }> {
  const home = await mkdtemp(join(tmpdir(), 'syl79-'));
  t.after(async () => { await rm(home, { recursive: true, force: true }); });
  const tool = join(home, 'tool');
  await mkdir(tool);
  await writeFile(join(tool, 'scenario'), 'C31 supported\n');
  const program = join(tool, 'codex');
  await writeFile(program, `#!/bin/sh\nexec ${quote(process.execPath)} ${quote(cli)} dev stand-in ${quote(tool)} -- "$@"\n`, { mode: 0o700 });
  await mkdir(join(home, '.arbol'));
  await writeFile(join(home, '.arbol', 'arbol-codex-driver.json'), JSON.stringify({ toolPath: program }));
  return { home, tool, state: join(home, 'state'), env: { HOME: home, PATH: `${dirname(process.execPath)}:/usr/bin:/bin`, LANG: 'C', TMPDIR: home } };
}
export async function invoke(args: string[], env: ProcessEnv): Promise<{ code: number; stdout: string; stderr: string; result: any }> {
  try {
    const result = await exec(process.execPath, [cli, ...args], { env, timeout: 10000 });
    return { code: 0, ...result, result: JSON.parse(result.stdout) };
  } catch (error) {
    const failed = error as { code: number; stdout: string; stderr: string };
    return { ...failed, result: JSON.parse(failed.stdout) };
  }
}
export async function received(tool: string): Promise<any[]> {
  return (await readFile(join(tool, 'received.jsonl'), 'utf8')).trim().split('\n').map(line => JSON.parse(line));
}
