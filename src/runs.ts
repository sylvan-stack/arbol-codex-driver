import { createHash } from 'node:crypto';
import { link, readFile, readdir, rm, unlink } from 'node:fs/promises';
import { join } from 'node:path';
import { Chats } from './continuity.js';
import { Failure, errno } from './errors.js';
import { isObject } from './settings.js';
import { collectProcessGroups, endProcessGroups } from './process-groups.js';
import { fixedWait, ownerAlive, parseOwner, prepareFile, processOwner, readJson, writeJson } from './state.js';
import type { Owner, ProcessEnv, State } from './state.js';
export interface RunRecord {
  runId: string; subscriptionId: string; owner: Owner; startedAt: string;
  labels?: Record<string, string>; chatKey?: string; conversation?: string; continuedConversation?: string; tool?: Owner; cleanupOwner?: Owner;
}
const identicalOwner = (a: Owner | undefined, b: Owner | undefined): boolean =>
  a !== undefined && b !== undefined && a.pid === b.pid && a.startedAt === b.startedAt;
const sameReservation = (a: RunRecord, b: RunRecord): boolean => a.runId === b.runId && a.subscriptionId === b.subscriptionId &&
  a.startedAt === b.startedAt && identicalOwner(a.owner, b.owner);

export class Runs {
  constructor(readonly state: State, readonly env: ProcessEnv = process.env) {}
  path(id: string): string {
    if (!/^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$/.test(id)) throw new Failure('invalid_input', 'The run identifier is not a safe file name.');
    return join(this.state.directory, 'runs', id + '.json');
  }
  private parse(value: unknown, id: string): RunRecord {
    if (!isObject(value) || value.runId !== id || typeof value.subscriptionId !== 'string' ||
      typeof value.startedAt !== 'string' || !Number.isFinite(Date.parse(value.startedAt))) throw new Failure('internal', 'Malformed run record.');
    this.path(id); this.state.subscription(value.subscriptionId);
    parseOwner(value.owner);
    if (value.tool !== undefined) parseOwner(value.tool);
    if (value.cleanupOwner !== undefined) parseOwner(value.cleanupOwner);
    if (value.chatKey !== undefined && (typeof value.chatKey !== 'string' || !/^[a-f0-9]{64}$/.test(value.chatKey))) throw new Failure('internal', 'Malformed run chat key.');
    if (value.continuedConversation !== undefined && (typeof value.continuedConversation !== 'string' || !value.continuedConversation)) throw new Failure('internal', 'Malformed run conversation.');
    return value as unknown as RunRecord;
  }
  private async record(id: string): Promise<RunRecord | undefined> {
    const value = await readJson(this.path(id));
    return value === undefined ? undefined : this.parse(value, id);
  }
  async list(): Promise<RunRecord[]> {
    await this.state.clearUnfinishedWrites();
    const files = await readdir(join(this.state.directory, 'runs')).catch(error => { if (errno(error, 'ENOENT')) return []; throw error; });
    const result: RunRecord[] = [];
    for (const file of files) {
      if (!file.endsWith('.json') || file.startsWith('.')) continue;
      const record = await this.record(file.slice(0, -5));
      if (!record) continue;
      if (await ownerAlive(record.owner)) result.push(record);
      else await this.recover(record);
    }
    return result;
  }
  private async orphanGroups(record: RunRecord): Promise<Owner[]> {
    const directory = join(this.state.directory, 'tmp', record.runId);
    let tool = record.tool;
    if (!tool) {
      const content = await readFile(join(directory, 'tool-owner.txt'), 'utf8').catch(error => { if (errno(error, 'ENOENT')) return undefined; throw error; });
      if (content !== undefined) {
        const lines = content.trim().split('\n');
        if (lines.length !== 2 || !/^[1-9][0-9]*$/.test(lines[0]!)) throw new Failure('internal', 'Malformed tool process ledger.');
        const started = Date.parse(lines[1]!.trim() + ' UTC');
        if (!Number.isFinite(started)) throw new Failure('internal', 'Malformed tool process ledger.');
        tool = parseOwner({ pid: Number(lines[0]), startedAt: new Date(started).toISOString() });
      }
    }
    const ledger = await readJson(join(directory, 'shell-owners.json'));
    if (ledger !== undefined && !Array.isArray(ledger)) throw new Failure('internal', 'Malformed shell process ledger.');
    const groups = (ledger as unknown[] | undefined)?.map(parseOwner) ?? [];
    if (tool) groups.push(...await collectProcessGroups(tool));
    return groups;
  }
  private async recover(stale: RunRecord, deadline = performance.now() + fixedWait(20000, this.env)): Promise<void> {
    const owner = await processOwner(process.pid);
    if (!owner) throw new Failure('internal', 'Cannot identify the run cleanup owner.');
    while (true) {
      const claimed = await this.state.withSubscriptionLock(stale.subscriptionId, async () => {
        const current = await this.record(stale.runId);
        if (!current || !sameReservation(current, stale) || await ownerAlive(current.owner)) return undefined;
        if (current.cleanupOwner && await ownerAlive(current.cleanupOwner)) return 'waiting' as const;
        current.cleanupOwner = owner; await this.save(current); return current;
      }, this.env);
      if (!claimed) return;
      if (claimed === 'waiting') {
        if (performance.now() >= deadline) throw new Failure('internal', 'Another call did not finish recovering the run.');
        await new Promise<void>(resolve => setTimeout(resolve, fixedWait(50, this.env))); continue;
      }
      try {
        const remaining = await endProcessGroups(await this.orphanGroups(claimed), Math.min(deadline, performance.now() + fixedWait(10000, this.env)));
        if (remaining.length) throw new Failure('internal', 'Cannot end orphaned run process groups: ' + remaining.map(group => group.pid).join(', ') + '.');
        // The reservation stays present until scratch and its matching map entry
        // are gone. Re-check before each deletion so a replacement is untouched.
        const current = await this.record(claimed.runId);
        if (!current || !sameReservation(current, claimed) || !identicalOwner(current.cleanupOwner, owner) || await ownerAlive(current.owner)) return;
        await rm(join(this.state.directory, 'tmp', claimed.runId), { recursive: true, force: true });
        await this.state.withSubscriptionLock(claimed.subscriptionId, async () => {
          const current = await this.record(claimed.runId);
          if (!current || !sameReservation(current, claimed) || !identicalOwner(current.cleanupOwner, owner) || await ownerAlive(current.owner)) return;
          if (claimed.chatKey !== undefined && claimed.continuedConversation !== undefined) {
            const chats = new Chats(this.state);
            if ((await chats.entry(claimed.subscriptionId, claimed.chatKey))?.conversation === claimed.continuedConversation) {
              await rm(chats.path(claimed.subscriptionId, claimed.chatKey), { force: true });
            }
          }
          await this.remove(claimed.runId);
        }, this.env);
      } catch (error) {
        // Release only this election; never recreate a removed or reused run.
        await this.state.withSubscriptionLock(claimed.subscriptionId, async () => {
          const current = await this.record(claimed.runId);
          if (current && sameReservation(current, claimed) && identicalOwner(current.cleanupOwner, owner)) {
            delete current.cleanupOwner; await this.save(current);
          }
        }, this.env);
        throw error;
      }
      return;
    }
  }
  async reserve(request: { runId: string; subscriptionId: string; labels?: Record<string, string>; chatSessionId?: string }): Promise<RunRecord> {
    const owner = await processOwner(process.pid);
    if (!owner) throw new Failure('internal', 'Cannot identify the run owner.');
    const record: RunRecord = { runId: request.runId, subscriptionId: request.subscriptionId, owner, startedAt: new Date().toISOString(),
      ...(request.labels === undefined ? {} : { labels: request.labels }),
      ...(request.chatSessionId === undefined ? {} : { chatKey: createHash('sha256').update(request.chatSessionId).digest('hex') }) };
    const path = this.path(request.runId);
    const temporary = await prepareFile(path, JSON.stringify(record) + '\n');
    try { await link(temporary, path); }
    catch (error) { if (errno(error, 'EEXIST')) throw new Failure('in_use', 'That run identifier is already in use.'); throw error; }
    finally { await unlink(temporary); }
    return record;
  }
  save(record: RunRecord): Promise<void> { return writeJson(this.path(record.runId), record); }
  remove(id: string): Promise<void> { return rm(this.path(id), { force: true }); }
  async stop(id: string): Promise<void> {
    this.path(id);
    const record = (await this.list()).find(item => item.runId === id); if (!record) return;
    if (await ownerAlive(record.owner)) {
      try { process.kill(record.owner.pid, 'SIGTERM'); } catch (error) { if (!errno(error, 'ESRCH')) throw error; }
    }
    const deadline = performance.now() + fixedWait(20000, this.env);
    while (true) {
      const current = await this.record(id);
      if (!current || !sameReservation(current, record)) return;
      if (!(await ownerAlive(record.owner))) { await this.recover(current, deadline); return; }
      if (performance.now() >= deadline) throw new Failure('in_use', 'The run did not stop within twenty seconds.');
      await new Promise(resolve => setTimeout(resolve, fixedWait(50, this.env)));
    }
  }
}
