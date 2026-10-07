import { access, stat, mkdtemp, rm } from 'node:fs/promises';
import { constants } from 'node:fs';
import { resolve, join, delimiter } from 'node:path';
import { spawn } from 'node:child_process';
import { Failure, errno } from './errors.js';
import { cleanEnvironment } from './environment.js';
import { isObject } from './settings.js';
import { privateDirectory, readJson, writeJson } from './state.js';
import type { State } from './state.js';
import type { ProcessEnv, ToolInfo, ToolRecord } from './types.js';
export const OLDEST_SUPPORTED = '0.159.2';

// A version query has no work to save. End its entire group even if a wrapper
// ignores SIGTERM or starts children that keep stdout open after it has exited.
function versionOutput(path: string, env: ProcessEnv, home: string, signal?: AbortSignal): Promise<string> {
  return new Promise((resolve, reject) => {
    const child = spawn(path, ['--version'], { env, cwd: home, detached: process.platform !== 'win32', stdio: ['ignore', 'pipe', 'ignore'] });
    let output = '', bytes = 0, failure: Error | undefined;
    const endGroup = (): void => {
      if (!child.pid) return;
      try {
        if (process.platform === 'win32') child.kill('SIGKILL');
        else process.kill(-child.pid, 'SIGKILL');
      } catch (error) { if (!errno(error, 'ESRCH')) failure ??= error as Error; }
    };
    const stop = (): void => { failure ??= new Error('Version query stopped.'); endGroup(); };
    const timer = setTimeout(stop, 10000);
    signal?.addEventListener('abort', stop, { once: true });
    child.once('error', error => { failure = error; });
    child.once('exit', endGroup);
    child.stdout.on('data', (chunk: Buffer) => {
      bytes += chunk.length;
      if (bytes > 16 * 1024) stop();
      else output += chunk.toString('utf8');
    });
    child.once('close', code => {
      clearTimeout(timer);
      signal?.removeEventListener('abort', stop);
      if (failure) reject(failure);
      else if (code !== 0) reject(new Error('Version query failed.'));
      else resolve(output);
    });
    if (signal?.aborted) stop();
  });
}
export function supportedVersion(version: string): boolean {
  const parts = /^(\d+)\.(\d+)\.(\d+)$/.exec(version);
  if (!parts) return false;
  const wanted = OLDEST_SUPPORTED.split('.').map(Number);
  for (let i = 0; i < 3; i++) {
    const found = BigInt(parts[i + 1]!);
    const minimum = BigInt(wanted[i]!);
    if (found !== minimum) return found > minimum;
  }
  return true;
}
async function executable(path: string): Promise<boolean> {
  try { await access(path, constants.X_OK); return (await stat(path)).isFile(); }
  catch (error) { if (errno(error, 'ENOENT') || errno(error, 'ENOTDIR') || errno(error, 'EACCES')) return false; throw error; }
}
export async function findTool(toolPath: string | undefined, env: ProcessEnv): Promise<string | undefined> {
  const program = toolPath ?? 'codex';
  if (program.includes('/') || program.includes('\\')) {
    const path = resolve(program);
    return await executable(path) ? path : undefined;
  }
  for (const folder of (env.PATH ?? '').split(delimiter)) {
    const path = resolve(folder || '.', program);
    if (await executable(path)) return path;
  }
  return undefined;
}
export async function inspectTool(state: State, toolPath: string | undefined, env: ProcessEnv, signal?: AbortSignal): Promise<ToolInfo> {
  const info: ToolInfo = { name: 'codex', supported: false, oldestSupported: OLDEST_SUPPORTED };
  const path = await findTool(toolPath, env);
  if (path === undefined) return info;
  info.path = path;
  const metadata = await stat(path);
  const changedAt = metadata.mtime.toISOString();
  const cached = await readJson(join(state.directory, 'tool.json'));
  let version: string;
  if (isObject(cached) && cached.path === path && cached.size === metadata.size && cached.changedAt === changedAt &&
    typeof cached.version === 'string' && /^\d+\.\d+\.\d+$/.test(cached.version)) {
    version = cached.version;
  } else {
    const tempDirectory = join(state.directory, 'tmp');
    await privateDirectory(tempDirectory);
    const home = await mkdtemp(join(tempDirectory, 'version-'));
    try {
      let output: string;
      try {
        output = await versionOutput(path, cleanEnvironment(env, home, join(home, '.codex')), home, signal);
      } catch (error) {
        if (errno(error, 'ENOENT')) throw new Failure('tool_missing', `codex was not found; version not found, needed ${OLDEST_SUPPORTED}.`, { detail: { basis: 'fields', neededVersion: OLDEST_SUPPORTED }, remedy: 'Install codex.' });
        throw new Failure('tool_failed', `codex could not report its version at ${path}.`, { detail: { basis: 'fields', neededVersion: OLDEST_SUPPORTED } });
      }
      const match = /^\s*codex-cli\s+(\d+\.\d+\.\d+)\s*$/.exec(output);
      if (!match) throw new Failure('tool_failed', 'codex returned an unrecognised version record.', { detail: { basis: 'fields', neededVersion: OLDEST_SUPPORTED } });
      version = match[1]!;
      const record: ToolRecord = { path, size: metadata.size, changedAt, version, askedAt: new Date().toISOString() };
      await writeJson(join(state.directory, 'tool.json'), record);
    } finally { await rm(home, { recursive: true, force: true }); }
  }
  info.version = version;
  info.supported = supportedVersion(version);
  return info;
}
export function requireTool(tool: ToolInfo): void {
  if (!tool.path) throw new Failure('tool_missing', `codex was not found; version not found, needed ${OLDEST_SUPPORTED}.`, { detail: { basis: 'fields', neededVersion: OLDEST_SUPPORTED }, remedy: 'Install codex.' });
  if (!tool.supported) throw new Failure('tool_unsupported', `codex ${tool.version ?? 'unknown'} is unsupported; needed ${OLDEST_SUPPORTED} or newer.`, { detail: { basis: 'fields', toolVersion: tool.version ?? 'unknown', neededVersion: OLDEST_SUPPORTED }, remedy: 'Update codex.' });
}
