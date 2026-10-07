import { createHash } from 'node:crypto';
import { link, readdir, rm, unlink } from 'node:fs/promises';
import { join } from 'node:path';
import { Failure, errno } from './errors.js';
import { isObject } from './settings.js';
import { fixedWait, ownerAlive, parseOwner, prepareFile, processOwner, readJson, writeJson } from './state.js';
import type { Owner, State } from './state.js';
export interface RunRecord {
  runId: string; subscriptionId: string; owner: Owner; startedAt: string;
  labels?: Record<string, string>; chatKey?: string; conversation?: string; tool?: Owner;
}
export class Runs {
  constructor(readonly state: State) {}
  path(id: string): string {
    if (!/^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$/.test(id)) throw new Failure('invalid_input', 'The run identifier is not a safe file name.');
    return join(this.state.directory, 'runs', id + '.json');
  }
  async list(): Promise<RunRecord[]> {
    const files = await readdir(join(this.state.directory, 'runs')).catch(error => { if (errno(error, 'ENOENT')) return []; throw error; });
    const result: RunRecord[] = [];
    for (const file of files) {
      if (!file.endsWith('.json') || file.startsWith('.')) continue;
      const value = await readJson(join(this.state.directory, 'runs', file));
      if (value === undefined) continue;
      if (!isObject(value) || typeof value.runId !== 'string' || file !== value.runId + '.json' || typeof value.subscriptionId !== 'string') throw new Failure('internal', 'Malformed run record.');
      this.path(value.runId); this.state.subscription(value.subscriptionId);
      const record = value as unknown as RunRecord;
      if (await ownerAlive(parseOwner(record.owner))) result.push(record);
      else await this.state.withSubscriptionLock(record.subscriptionId, async () => {
        const current = await readJson(this.path(record.runId));
        if (!isObject(current) || JSON.stringify(current.owner) !== JSON.stringify(record.owner) || await ownerAlive(parseOwner(current.owner))) return;
        if (record.tool && await ownerAlive(parseOwner(record.tool))) {
          try { process.kill(process.platform === 'win32' ? record.tool.pid : -record.tool.pid, 'SIGKILL'); }
          catch (error) { if (!errno(error, 'ESRCH')) throw error; }
        }
        await rm(join(this.state.directory, 'tmp', record.runId), { recursive: true, force: true });
        await this.remove(record.runId);
      });
    }
    return result;
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
    const deadline = performance.now() + fixedWait(20000);
    while (await readJson(this.path(id)) !== undefined) {
      if (!(await ownerAlive(record.owner))) { await this.list(); return; }
      if (performance.now() >= deadline) throw new Failure('in_use', 'The run did not stop within twenty seconds.');
      await new Promise(resolve => setTimeout(resolve, fixedWait(50)));
    }
  }
}
