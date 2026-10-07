import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { Failure, errno } from './errors.js';
import { fixedWait, parseOwner } from './state.js';
import type { Owner } from './state.js';

const exec = promisify(execFile);
export interface ProcessSnapshot extends Owner { parentId: number; groupId: number; zombie: boolean }
const sameOwner = (actual: Owner, expected: Owner): boolean =>
  actual.pid === expected.pid && Math.abs(Date.parse(actual.startedAt) - Date.parse(expected.startedAt)) <= 2000;

async function processSnapshot(deadline: number): Promise<ProcessSnapshot[]> {
  const { stdout } = await exec('/bin/ps', ['-axo', 'pid=,ppid=,pgid=,stat=,lstart='], {
    env: { PATH: '/usr/bin:/bin', LC_ALL: 'C', TZ: 'UTC' },
    timeout: Math.max(1, Math.min(1000, Math.ceil(deadline - performance.now()))), maxBuffer: 4 * 1024 * 1024,
  });
  return stdout.split('\n').filter(line => line.trim()).map(line => {
    const row = /^\s*(\d+)\s+(\d+)\s+(\d+)\s+(\S+)\s+(.+?)\s*$/.exec(line);
    const started = row && Date.parse(row[5] + ' UTC');
    if (!row || !Number.isFinite(started)) throw new Failure('internal', 'Cannot read the process table for run cleanup.');
    return { pid: Number(row[1]), parentId: Number(row[2]), groupId: Number(row[3]),
      zombie: row[4]!.startsWith('Z'), startedAt: new Date(started as number).toISOString() };
  });
}

/** A departed leader leaves a group behind; a reused leader never grants ownership. */
export function survivingProcessGroups(owners: readonly Owner[], table: readonly ProcessSnapshot[]): Owner[] {
  const seen = new Set<number>();
  return owners.filter(owner => {
    parseOwner(owner);
    if (seen.has(owner.pid)) return false;
    seen.add(owner.pid);
    const leader = table.find(row => row.pid === owner.pid);
    if (leader && (!sameOwner(leader, owner) || leader.groupId !== owner.pid)) return false;
    return table.some(row => row.groupId === owner.pid && !row.zombie);
  });
}

/** Capture OS identities while ancestry still exists, including vendor shell groups. */
export function descendantProcessGroups(owner: Owner, table: readonly ProcessSnapshot[]): Owner[] {
  parseOwner(owner);
  const process = table.find(row => row.pid === owner.pid);
  if (process && (!sameOwner(process, owner) || process.groupId !== owner.pid)) return [];
  const initial = process ? table.filter(row => row.groupId === process.groupId) :
    survivingProcessGroups([owner], table).length ? table.filter(row => row.groupId === owner.pid) : [];
  if (!initial.length) return [];
  const descendants = new Set(initial.map(row => row.pid));
  let changed = true;
  while (changed) {
    changed = false;
    for (const row of table) {
      if (!descendants.has(row.pid) && descendants.has(row.parentId)) { descendants.add(row.pid); changed = true; }
    }
  }
  const groups = new Set(table.filter(row => descendants.has(row.pid) && !row.zombie).map(row => row.groupId));
  return [...groups].flatMap(groupId => {
    const leader = table.find(row => row.pid === groupId);
    if (leader) return [{ pid: leader.pid, startedAt: leader.startedAt }];
    // The initial group may have lost its leader. Its recorded identity is the
    // only identity we can safely retain; other departed groups need a ledger.
    return groupId === owner.pid ? [{ ...owner }] : [];
  });
}

export async function collectProcessGroups(owner: Owner): Promise<Owner[]> {
  return descendantProcessGroups(owner, await processSnapshot(performance.now() + 1000));
}

/** End verified groups and await every member, including children holding no pipes. */
export async function endProcessGroups(owners: readonly Owner[], deadline = performance.now() + fixedWait(10000)): Promise<Owner[]> {
  const known = new Map(owners.map(owner => { const parsed = parseOwner(owner); return [parsed.pid, parsed] as const; }));
  if (!known.size) return [];
  let remaining = [...known.values()];
  const terminated = new Set<number>();
  const forceAt = Math.min(deadline, performance.now() + fixedWait(2000));
  while (performance.now() < deadline) {
    let table: ProcessSnapshot[];
    try { table = await processSnapshot(deadline); }
    catch (error) { if (performance.now() >= deadline) return remaining; throw error; }
    remaining = survivingProcessGroups([...known.values()], table);
    for (const owner of remaining) {
      for (const childGroup of descendantProcessGroups(owner, table)) {
        if (!known.has(childGroup.pid)) known.set(childGroup.pid, childGroup);
      }
    }
    remaining = survivingProcessGroups([...known.values()], table);
    if (!remaining.length) return [];
    for (const owner of remaining) {
      const forced = performance.now() >= forceAt;
      if (!forced && terminated.has(owner.pid)) continue;
      try { process.kill(process.platform === 'win32' ? owner.pid : -owner.pid, forced ? 'SIGKILL' : 'SIGTERM'); }
      catch (error) { if (!errno(error, 'ESRCH')) throw error; }
      terminated.add(owner.pid);
    }
    await new Promise<void>(resolve => setTimeout(resolve, Math.min(fixedWait(50), Math.max(1, deadline - performance.now()))));
  }
  return remaining;
}

export async function endProcessGroup(owner: Owner, deadline?: number): Promise<Owner[]> {
  return endProcessGroups(await collectProcessGroups(owner), deadline);
}
