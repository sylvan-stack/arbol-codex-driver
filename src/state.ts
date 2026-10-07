import { randomUUID } from 'node:crypto';
import { execFile } from 'node:child_process';
import { chmod, link, mkdir, open, readFile, readdir, rename, stat, unlink } from 'node:fs/promises';
import type { Stats } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { promisify } from 'node:util';
import { DriverFailure, errno } from './errors.js';

export interface Owner { pid: number; startedAt: string }
export type ProcessEnv = Record<string, string | undefined>;

const exec = promisify(execFile);
const isObject = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === 'object' && !Array.isArray(value);
export const DATA_FORMAT = 1;
export const defaultStateDirectory = (home: string): string =>
  join(home, 'Library', 'Application Support', 'Arbol', 'drivers', 'codex');

export function fixedWait(milliseconds: number, env: ProcessEnv = process.env): number {
  if (env.ARBOL_TEST_TIME_SCALE === undefined) return milliseconds;
  const scale = Number(env.ARBOL_TEST_TIME_SCALE);
  if (!Number.isFinite(scale) || scale <= 0) {
    throw new DriverFailure('invalid_input', 'ARBOL_TEST_TIME_SCALE must be a positive finite number.');
  }
  return milliseconds / scale;
}

export async function privateDirectory(path: string): Promise<void> {
  await mkdir(path, { recursive: true, mode: 0o700 });
  await chmod(path, 0o700);
}

// Preparing beside the destination keeps the eventual rename on one filesystem.
export async function prepareFile(path: string, content: string): Promise<string> {
  await privateDirectory(dirname(path));
  const temporary = join(dirname(path), `.write-${randomUUID()}`);
  const file = await open(temporary, 'wx', 0o600);
  try {
    await file.writeFile(content, 'utf8');
    await file.sync();
  } catch (error) {
    await unlink(temporary).catch(() => {});
    throw error;
  } finally {
    await file.close();
  }
  return temporary;
}

export async function atomicWrite(path: string, content: string): Promise<void> {
  const temporary = await prepareFile(path, content);
  try { await rename(temporary, path); }
  finally { await removeIfPresent(temporary); }
}

export const writeJson = async (path: string, value: unknown): Promise<void> =>
  atomicWrite(path, JSON.stringify(value) + '\n');

export async function readJson(path: string): Promise<unknown | undefined> {
  try { return JSON.parse(await readFile(path, 'utf8')) as unknown; }
  catch (error) {
    if (errno(error, 'ENOENT')) return undefined;
    throw new DriverFailure('internal', `Cannot read state file ${path}.`);
  }
}

export function parseOwner(value: unknown): Owner {
  if (!isObject(value) || !Number.isInteger(value.pid) || (value.pid as number) <= 0 ||
      typeof value.startedAt !== 'string' || !Number.isFinite(Date.parse(value.startedAt))) {
    throw new DriverFailure('internal', 'A process owner record is malformed.');
  }
  return { pid: value.pid as number, startedAt: value.startedAt };
}

export async function processOwner(pid: number): Promise<Owner | undefined> {
  if (!Number.isInteger(pid) || pid <= 0) throw new DriverFailure('internal', 'A process identifier is malformed.');
  try {
    const { stdout } = await exec('/bin/ps', ['-p', String(pid), '-o', 'lstart='], {
      env: { PATH: '/usr/bin:/bin', LC_ALL: 'C', TZ: 'UTC' }, timeout: 5000, maxBuffer: 4096,
    });
    const started = Date.parse(stdout.trim() + ' UTC');
    if (!Number.isFinite(started)) throw new DriverFailure('internal', `Cannot read the start time of process ${pid}.`);
    return { pid, startedAt: new Date(started).toISOString() };
  } catch (error) {
    if (isObject(error) && error.code === 1) return undefined;
    throw new DriverFailure('internal', `Cannot read the start time of process ${pid}.`);
  }
}

export async function ownerAlive(owner: Owner): Promise<boolean> {
  const parsed = parseOwner(owner);
  const current = await processOwner(parsed.pid);
  return current !== undefined && Math.abs(Date.parse(current.startedAt) - Date.parse(parsed.startedAt)) <= 2000;
}

async function removeIfPresent(path: string): Promise<void> {
  await unlink(path).catch((error: unknown) => { if (!errno(error, 'ENOENT')) throw error; });
}

async function readLock(path: string): Promise<{ snapshot: Stats; owner: Owner } | undefined> {
  const file = await open(path, 'r').catch((error: unknown) => {
    if (errno(error, 'ENOENT')) return undefined;
    throw error;
  });
  if (!file) return undefined;
  try {
    const snapshot = await file.stat();
    let value: unknown;
    try { value = JSON.parse(await file.readFile('utf8')) as unknown; }
    catch { throw new DriverFailure('internal', `Malformed lock ${path}.`); }
    if (!isObject(value)) throw new DriverFailure('internal', `Malformed lock ${path}.`);
    return { snapshot, owner: parseOwner(value.owner) };
  } finally { await file.close(); }
}

// Each stale inode elects one remover. If that remover died, removing its election
// is itself elected by inode, so simultaneous recovery cannot erase a new owner.
async function reclaimDeadFile(path: string, snapshot: Stats, temporary: string): Promise<void> {
  const election = join(dirname(path), `.write-reap-${snapshot.ino}`);
  let elected = false;
  try {
    await link(temporary, election);
    elected = true;
    const current = await stat(path).catch((error: unknown) => {
      if (errno(error, 'ENOENT')) return undefined;
      throw error;
    });
    if (current?.ino === snapshot.ino && current.dev === snapshot.dev) await removeIfPresent(path);
  } catch (error) {
    if (errno(error, 'EEXIST')) {
      const reaper = await readLock(election);
      if (reaper && !(await ownerAlive(reaper.owner))) {
        await reclaimDeadFile(election, reaper.snapshot, temporary);
      }
    } else if (!errno(error, 'ENOENT')) throw error;
  } finally {
    if (elected) await removeIfPresent(election);
  }
}

export class State {
  readonly directory: string;
  constructor(directory: string) { this.directory = resolve(directory); }

  async initialize(): Promise<void> {
    const path = join(this.directory, 'format');
    const check = async (): Promise<boolean> => {
      let content: string;
      try { content = await readFile(path, 'utf8'); }
      catch (error) { if (errno(error, 'ENOENT')) return false; throw error; }
      const value = content.trim();
      if (!/^[1-9][0-9]*$/.test(value)) throw new DriverFailure('internal', `State format in ${path} is malformed.`);
      const number = BigInt(value);
      if (number > BigInt(DATA_FORMAT)) {
        throw new DriverFailure('state_newer', `State format ${number} is newer than supported format ${DATA_FORMAT}.`, {
          remedy: 'Run the Build that wrote this state, or a newer one.',
        });
      }
      return true;
    };
    // Check before mkdir/chmod so an incompatible state remains untouched.
    if (await check()) {
      await privateDirectory(this.directory);
      await chmod(path, 0o600);
      return;
    }
    await privateDirectory(this.directory);
    const temporary = await prepareFile(path, `${DATA_FORMAT}\n`);
    try { await link(temporary, path); }
    catch (error) { if (!errno(error, 'EEXIST')) throw error; }
    finally { await removeIfPresent(temporary); }
    await check();
  }

  subscription(id: string): string {
    if (!/^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$/.test(id)) {
      throw new DriverFailure('invalid_input', 'The Subscription identifier is not a safe file name.');
    }
    return join(this.directory, 'subscriptions', id);
  }

  async clearUnfinishedWrites(): Promise<void> {
    const visit = async (directory: string, depth: number): Promise<void> => {
      const entries = await readdir(directory, { withFileTypes: true }).catch((error: unknown) => {
        if (errno(error, 'ENOENT')) return [];
        throw error;
      });
      for (const entry of entries) {
        const path = join(directory, entry.name);
        if (entry.isFile() && entry.name.startsWith('.write-')) {
          const info = await stat(path).catch((error: unknown) => {
            if (errno(error, 'ENOENT')) return undefined;
            throw error;
          });
          if (info && Date.now() - info.mtimeMs > 60000) await removeIfPresent(path);
        } else if (depth > 0 && entry.isDirectory() && entry.name !== 'home' && entry.name !== 'tmp') {
          await visit(path, depth - 1);
        }
      }
    };
    await visit(this.directory, 3);
  }

  async withSubscriptionLock<T>(id: string, change: () => Promise<T>, env: ProcessEnv = process.env): Promise<T> {
    const directory = this.subscription(id);
    const timeout = fixedWait(10000, env);
    const retry = fixedWait(50, env);
    await privateDirectory(join(this.directory, 'subscriptions'));
    await privateDirectory(directory);
    const path = join(directory, 'lock');
    const owner = await processOwner(process.pid);
    if (!owner) throw new DriverFailure('internal', 'Cannot identify the Driver process.');
    const temporary = await prepareFile(path, JSON.stringify({ owner }) + '\n');
    const deadline = performance.now() + timeout;
    let acquired = false;
    let takenBy: Owner | undefined;
    try {
      while (!acquired) {
        try { await link(temporary, path); acquired = true; }
        catch (error) {
          if (!errno(error, 'EEXIST')) throw error;
          const existing = await readLock(path);
          if (!existing) continue;
          takenBy = existing.owner;
          if (!(await ownerAlive(takenBy))) await reclaimDeadFile(path, existing.snapshot, temporary);
          if (performance.now() >= deadline) {
            throw new DriverFailure('internal', `Subscription lock timed out after ${timeout} milliseconds; owner PID ${takenBy.pid}, started ${takenBy.startedAt}.`);
          }
          await new Promise<void>(resolve => setTimeout(resolve, retry));
        }
      }
      return await change();
    } finally {
      if (acquired) await removeIfPresent(path);
      await removeIfPresent(temporary);
    }
  }
}
