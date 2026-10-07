import { randomUUID } from 'node:crypto';
import { readdir, rm, stat, unlink } from 'node:fs/promises';
import { join } from 'node:path';
import { AppServer } from './app-server.js';
import { normalizeAccount, normalizeUsage, readModelCatalog, builtinModelCatalog } from './catalog.js';
import type { UsageReport, ModelCatalog } from './catalog.js';
import { Failure, errno, safeFailure } from './errors.js';
import type { DriverError } from './errors.js';
import { isObject } from './settings.js';
import type { DriverSettings, Notice } from './settings.js';
import { ownerAlive, parseOwner, privateDirectory, processOwner, readJson, writeJson, fixedWait } from './state.js';
import type { State, Owner } from './state.js';
import { inspectTool, requireTool } from './tool.js';
import type { ProcessEnv } from './types.js';

export interface Subscription {
  id: string; family: 'chatgpt'; label: string; auth: 'vendor_login';
  state: 'signed_out' | 'signing_in' | 'signed_in' | 'needs_attention';
  account?: { name?: string; email?: string; organization?: string; plan?: string };
  problem?: DriverError; settings: Record<string, unknown>; lastUsage?: UsageReport;
  createdAt: string; updatedAt: string; checkedAt?: string;
}
type RecordState = Omit<Subscription, 'settings' | 'state'> & { state: 'signed_out' | 'signed_in' | 'needs_attention' };
interface Progress {
  owner: Owner; tool?: Owner; attempt: string; operation: 'sign_in' | 'sign_out' | 'remove';
  expiresAt: string; byCode?: boolean; stopReason?: 'replaced' | 'signed_out';
}
export const families = [{ id: 'chatgpt', label: 'ChatGPT', auth: 'vendor_login',
  settings: { type: 'object', properties: {}, additionalProperties: false } }];
const now = (): string => new Date().toISOString();
const delay = async (ms: number): Promise<void> => new Promise(resolve => setTimeout(resolve, ms));
const missing = async (file: string): Promise<void> => unlink(file).catch((error: unknown) => { if (!errno(error, 'ENOENT')) throw error; });

function parseRecord(value: unknown, id: string): RecordState {
  const bad = (): never => { throw new Failure('internal', `Malformed Subscription record for ${id}.`); };
  if (!isObject(value) || value.id !== id || value.family !== 'chatgpt' || value.auth !== 'vendor_login' ||
    typeof value.label !== 'string' || !value.label || !['signed_out', 'signed_in', 'needs_attention'].includes(value.state as string) ||
    !['createdAt', 'updatedAt'].every(key => typeof value[key] === 'string' && Number.isFinite(Date.parse(value[key] as string)))) bad();
  const record = value as unknown as RecordState;
  if (Object.keys(value as object).some(key => !['id', 'family', 'label', 'auth', 'state', 'account', 'problem', 'lastUsage', 'createdAt', 'updatedAt', 'checkedAt'].includes(key))) bad();
  if ((record.state === 'needs_attention') !== (record.problem !== undefined)) bad();
  if (record.problem !== undefined && (!isObject(record.problem) || record.problem.code !== 'credential_rejected' ||
    typeof record.problem.message !== 'string' || typeof record.problem.retryable !== 'boolean')) bad();
  if (record.checkedAt !== undefined && (typeof record.checkedAt !== 'string' || !Number.isFinite(Date.parse(record.checkedAt)))) bad();
  if (record.account !== undefined && (!isObject(record.account) || Object.entries(record.account).some(([key, item]) =>
    !['name', 'email', 'organization', 'plan'].includes(key) || typeof item !== 'string'))) bad();
  if (record.lastUsage !== undefined && (!isObject(record.lastUsage) || record.lastUsage.outcome !== 'ok' ||
    typeof record.lastUsage.fetchedAt !== 'string' || !Number.isFinite(Date.parse(record.lastUsage.fetchedAt)) || !Array.isArray(record.lastUsage.windows))) bad();
  return record;
}
function parseProgress(value: unknown): Progress {
  if (!isObject(value) || typeof value.expiresAt !== 'string' || !Number.isFinite(Date.parse(value.expiresAt)) ||
    (value.operation !== undefined && !['sign_in', 'sign_out', 'remove'].includes(value.operation as string))) {
    throw new Failure('internal', 'Malformed sign-in record.');
  }
  const owner = parseOwner(value.owner);
  const tool = value.tool === undefined ? undefined : parseOwner(value.tool);
  // Earlier progress records had no attempt token; owner identity is their token.
  return { ...value, owner, ...(tool ? { tool } : {}), attempt: typeof value.attempt === 'string' ? value.attempt : `${owner.pid}:${owner.startedAt}`,
    operation: value.operation as Progress['operation'] ?? 'sign_in' } as Progress;
}

export class Subscriptions {
  constructor(readonly state: State, readonly settings: DriverSettings, readonly notices: Notice[], readonly settingsFile: string,
    readonly env: ProcessEnv = process.env, readonly signal?: AbortSignal) {}
  private file(id: string, name: string): string { return join(this.state.subscription(id), name); }
  async record(id: string): Promise<RecordState> {
    const value = await readJson(this.file(id, 'record.json'));
    if (value !== undefined) return parseRecord(value, id);
    if (id !== 'chatgpt') throw new Failure('not_found', 'Subscription was not found.');
    const createdAt = (await stat(join(this.state.directory, 'format'))).birthtime.toISOString();
    return { id, family: 'chatgpt', label: 'ChatGPT', auth: 'vendor_login', state: 'signed_out', createdAt, updatedAt: createdAt };
  }
  private async progress(id: string): Promise<Progress | undefined> {
    const value = await readJson(this.file(id, 'sign-in.json'));
    return value === undefined ? undefined : parseProgress(value);
  }
  async get(id: string): Promise<Subscription> {
    const record = await this.record(id);
    await this.reap(id);
    for (const key of Object.keys(this.settings.subscriptions?.[id]?.settings ?? {})) {
      const message = `Ignoring unknown setting ${this.settingsFile}: subscriptions.${id}.settings.${key}.`;
      if (!this.notices.some(n => n.message === message)) this.notices.push({ code: 'unknown_setting', message });
    }
    const result: Subscription = { ...record, settings: {} };
    const pending = await this.progress(id);
    if (pending?.operation === 'sign_in' && await ownerAlive(pending.owner)) { result.state = 'signing_in'; delete result.problem; }
    return result;
  }
  private async ids(): Promise<string[]> {
    const ids = new Set(['chatgpt']);
    const entries = await readdir(join(this.state.directory, 'subscriptions'), { withFileTypes: true }).catch((error: unknown) => {
      if (errno(error, 'ENOENT')) return []; throw error;
    });
    for (const entry of entries) if (entry.isDirectory() && await readJson(this.file(entry.name, 'record.json')) !== undefined) ids.add(entry.name);
    return [...ids];
  }
  async list(): Promise<Subscription[]> { return Promise.all((await this.ids()).map(id => this.get(id))); }
  async create(family: unknown, label: unknown, explicitId?: string): Promise<Subscription> {
    if (family !== 'chatgpt') throw new Failure('invalid_input', 'Choose the Subscription family chatgpt.');
    if (typeof label !== 'string' || !label) throw new Failure('invalid_input', 'Give the new Subscription a label.');
    for (let number = 2; ; number++) {
      const id = explicitId ?? `chatgpt-${number}`;
      const made = await this.state.withSubscriptionLock(id, async () => {
        if (id === 'chatgpt' || await readJson(this.file(id, 'record.json')) !== undefined || await this.progress(id)) return false;
        const time = now();
        await privateDirectory(this.file(id, 'home'));
        await writeJson(this.file(id, 'record.json'), { id, family: 'chatgpt', label, auth: 'vendor_login', state: 'signed_out', createdAt: time, updatedAt: time });
        return true;
      }, this.env);
      if (made) return this.get(id);
      if (explicitId !== undefined) throw new Failure('in_use', 'That Subscription identifier already exists.');
    }
  }
  private async killTool(owner: Owner | undefined): Promise<void> {
    if (!owner || !(await ownerAlive(owner))) return;
    try { process.kill(process.platform === 'win32' ? owner.pid : -owner.pid, 'SIGKILL'); }
    catch (error) { if (!errno(error, 'ESRCH')) throw error; }
  }
  async reap(id: string): Promise<void> {
    const pending = await this.progress(id);
    if (!pending || await ownerAlive(pending.owner)) return;
    await this.killTool(pending.tool);
    await this.state.withSubscriptionLock(id, async () => {
      const current = await this.progress(id);
      if (current?.attempt === pending.attempt && !(await ownerAlive(current.owner))) await missing(this.file(id, 'sign-in.json'));
    }, this.env);
  }
  async update(id: string, label?: string): Promise<Subscription> {
    await this.get(id); await this.reap(id); await this.state.clearUnfinishedWrites();
    if (label === undefined) return this.get(id);
    if (!label) throw new Failure('invalid_input', 'Give the Subscription a non-empty label.');
    await this.state.withSubscriptionLock(id, async () => {
      const current = await this.record(id);
      await privateDirectory(this.file(id, 'home'));
      await writeJson(this.file(id, 'record.json'), { ...current, label, updatedAt: now() });
    }, this.env);
    return this.get(id);
  }
  async requireSignedIn(id: string): Promise<Subscription> {
    const item = await this.get(id);
    if (item.state !== 'signed_in') throw new Failure('not_signed_in', 'Sign in to this Subscription first.', { remedy: 'Sign in again.' });
    return item;
  }
  private async start(id: string, onSpawn?: (owner: Owner) => Promise<void>, signal = this.signal): Promise<AppServer> {
    const tool = await inspectTool(this.state, this.settings.toolPath, this.env, signal); requireTool(tool);
    return AppServer.start({ toolPath: tool.path!, home: this.file(id, 'home'), env: this.env,
      ...(signal ? { signal } : {}), ...(onSpawn ? { onSpawn } : {}) });
  }
  private waitOptions(): { signal?: AbortSignal } { return this.signal ? { signal: this.signal } : {}; }
  private rejection(message = 'Codex rejected this ChatGPT login.'): Failure {
    return new Failure('credential_rejected', message, { remedy: 'Sign in again.' });
  }
  // A network answer is committed only if the login it checked is still current.
  private async merge(initial: Subscription, fields: Partial<RecordState>): Promise<Subscription> {
    await this.state.withSubscriptionLock(initial.id, async () => {
      let current: RecordState;
      try { current = await this.record(initial.id); }
      catch (error) { if (error instanceof Failure && error.result.code === 'not_found') return; throw error; }
      if (current.state !== initial.state || current.checkedAt !== initial.checkedAt || current.createdAt !== initial.createdAt || await this.progress(initial.id)) {
        throw new Failure('in_use', 'The Subscription changed while Codex was answering. Try again.');
      }
      const next = { ...current, ...fields, updatedAt: now() };
      if (next.state !== 'needs_attention') delete next.problem;
      await writeJson(this.file(initial.id, 'record.json'), next);
    }, this.env);
    return this.get(initial.id);
  }
  async check(id: string): Promise<Subscription> {
    const initial = await this.get(id);
    if (initial.state === 'signed_out') throw new Failure('not_signed_in', 'Sign in to this Subscription first.', { remedy: 'Sign in again.' });
    let server: AppServer | undefined;
    try {
      server = await this.start(id);
      const account = normalizeAccount(await server.request('account/read', { refreshToken: true }, this.waitOptions()));
      this.signal?.throwIfAborted();
      return this.merge(initial, account ? { state: 'signed_in', account, checkedAt: now() } :
        { state: 'needs_attention', problem: this.rejection('The Codex home has no ChatGPT account.').result, checkedAt: now() });
    } catch (error) {
      if (error instanceof Failure && error.result.code === 'credential_rejected') return this.merge(initial, { state: 'needs_attention', problem: error.result, checkedAt: now() });
      throw error;
    } finally { await server?.close(); }
  }
  async usage(id: string): Promise<UsageReport> {
    const initial = await this.get(id);
    if (initial.state !== 'signed_in') return { outcome: 'needs_sign_in', fetchedAt: now(), windows: [], message: 'Sign in to this Subscription first.' };
    let server: AppServer | undefined;
    try {
      server = await this.start(id);
      const usage = normalizeUsage(await server.request('account/rateLimits/read', {}, this.waitOptions()), initial.account?.plan);
      this.signal?.throwIfAborted();
      if (usage.outcome === 'ok') await this.merge(initial, { lastUsage: usage });
      return usage;
    } catch (error) {
      if (error instanceof Failure && error.result.code === 'credential_rejected') {
        await this.merge(initial, { state: 'needs_attention', problem: error.result, checkedAt: now() });
        return { outcome: 'needs_sign_in', fetchedAt: now(), windows: [], message: error.message };
      }
      if (error instanceof Failure && ['tool_missing', 'tool_unsupported'].includes(error.result.code)) throw error;
      return { outcome: 'unavailable', fetchedAt: now(), windows: [], message: safeFailure(error).message };
    } finally { await server?.close(); }
  }
  async models(id: string): Promise<ModelCatalog> {
    const initial = await this.requireSignedIn(id);
    let server: AppServer | undefined;
    try {
      server = await this.start(id);
      const catalog = await readModelCatalog({ request: <T = unknown>(method: string, params: unknown) => server!.request<T>(method, params, this.waitOptions()) });
      this.signal?.throwIfAborted();
      return catalog;
    }
    catch (error) {
      if (error instanceof Failure && error.result.code === 'credential_rejected') {
        await this.merge(initial, { state: 'needs_attention', problem: error.result, checkedAt: now() }); throw error;
      }
      if (error instanceof Failure && ['tool_missing', 'tool_unsupported'].includes(error.result.code)) throw error;
      this.signal?.throwIfAborted();
      return builtinModelCatalog();
    } finally { await server?.close(); }
  }
  private async stopPending(id: string, pending: Progress, stopReason: 'replaced' | 'signed_out' = 'replaced'): Promise<void> {
    if (!(await ownerAlive(pending.owner))) { await this.reap(id); return; }
    await this.state.withSubscriptionLock(id, async () => {
      const current = await this.progress(id);
      if (current?.attempt === pending.attempt) await writeJson(this.file(id, 'sign-in.json'), { ...current, stopReason });
    }, this.env);
    if (await ownerAlive(pending.owner)) {
      try { process.kill(pending.owner.pid, 'SIGTERM'); } catch (error) { if (!errno(error, 'ESRCH')) throw error; }
    }
    const deadline = performance.now() + fixedWait(5000, this.env);
    while ((await this.progress(id))?.attempt === pending.attempt) {
      if (!(await ownerAlive(pending.owner))) { await this.reap(id); return; }
      if (performance.now() > deadline) throw new Failure('in_use', 'The previous account operation did not stop.');
      await delay(fixedWait(25, this.env));
    }
  }
  private async reserve(id: string, operation: Progress['operation'], byCode = false): Promise<Progress> {
    await this.get(id); await this.state.clearUnfinishedWrites();
    const owner = await processOwner(process.pid);
    if (!owner) throw new Failure('internal', 'Cannot identify the Driver process.');
    const progress: Progress = { owner, attempt: randomUUID(), operation, byCode, expiresAt: new Date(Date.now() + fixedWait(300000, this.env)).toISOString() };
    for (;;) {
      this.signal?.throwIfAborted(); await this.reap(id);
      const previous = await this.state.withSubscriptionLock(id, async () => {
        await this.record(id);
        const current = await this.progress(id);
        if (current) return current;
        const record = await this.record(id);
        if (operation === 'sign_in') {
          const cleared = { ...record, state: 'signed_out' as const, updatedAt: now(), checkedAt: now() };
          delete cleared.account; delete cleared.problem; delete cleared.lastUsage;
          await writeJson(this.file(id, 'record.json'), cleared);
        }
        await writeJson(this.file(id, 'sign-in.json'), progress);
        return undefined;
      }, this.env);
      if (!previous) return progress;
      // Destructive operations wait for each other; sign-in supersedes sign-in.
      if (previous.operation === 'sign_in') await this.stopPending(id, previous, operation === 'sign_in' ? 'replaced' : 'signed_out');
      else {
        const deadline = performance.now() + fixedWait(10000, this.env);
        while ((await this.progress(id))?.attempt === previous.attempt && await ownerAlive(previous.owner)) {
          this.signal?.throwIfAborted();
          if (performance.now() > deadline) throw new Failure('in_use', 'An account operation is still in progress.');
          await delay(fixedWait(50, this.env));
        }
      }
    }
  }
  private async finish(id: string, progress: Progress, fields?: Partial<RecordState>): Promise<void> {
    await this.state.withSubscriptionLock(id, async () => {
      const pending = await this.progress(id);
      if (pending?.attempt !== progress.attempt) {
        if (fields?.state === 'signed_in') throw new Failure('in_use', 'Another sign-in took its place.');
        return;
      }
      if (fields?.state === 'signed_in' && pending.stopReason) throw new Failure('in_use', 'Another sign-in took its place.');
      if (fields) {
        const current = await this.record(id); const next = { ...current, ...fields, updatedAt: now() };
        if (next.state === 'signed_out') { delete next.account; delete next.problem; delete next.lastUsage; }
        else if (next.state === 'signed_in') delete next.problem;
        await writeJson(this.file(id, 'record.json'), next);
      }
      await missing(this.file(id, 'sign-in.json'));
    }, this.env);
  }
  private async setTool(id: string, progress: Progress, tool: Owner): Promise<void> {
    await this.state.withSubscriptionLock(id, async () => {
      const current = await this.progress(id);
      if (current?.attempt !== progress.attempt) throw new Failure('in_use', 'Another account operation took its place.');
      await writeJson(this.file(id, 'sign-in.json'), { ...current, tool });
    }, this.env);
  }
  private async localLogin(id: string, own: Progress): Promise<void> {
    // Every contender publishes before scanning. A newer contender supersedes
    // older local logins, including those published simultaneously in another home.
    const rank = (p: Progress): string => `${p.owner.startedAt}:${String(p.owner.pid).padStart(12, '0')}:${p.attempt}`;
    for (const otherId of await this.ids()) {
      if (otherId === id) continue;
      const pending = await this.progress(otherId);
      if (pending?.operation !== 'sign_in' || pending.byCode || !(await ownerAlive(pending.owner))) continue;
      if (rank(pending) < rank(own)) await this.stopPending(otherId, pending);
      else throw new Failure('in_use', 'Another local ChatGPT sign-in took its place.');
    }
  }
  async signIn(id: string, byCode: boolean, emit: (step: unknown) => void): Promise<number> {
    let progress: Progress | undefined; let server: AppServer | undefined; let loginId: string | undefined; let success = false;
    const timeout = new AbortController(); let timer: NodeJS.Timeout | undefined;
    try {
      progress = await this.reserve(id, 'sign_in', byCode);
      timer = setTimeout(() => timeout.abort(), Math.max(1, Date.parse(progress.expiresAt) - Date.now()));
      const signal = this.signal ? AbortSignal.any([this.signal, timeout.signal]) : timeout.signal;
      if (!byCode) await this.localLogin(id, progress);
      signal.throwIfAborted();
      const own = progress;
      server = await this.start(id, tool => this.setTool(id, own, tool), signal);
      const result = await server.request('account/login/start', { type: byCode ? 'chatgptDeviceCode' : 'chatgpt' }, { signal });
      if (!isObject(result) || typeof result.loginId !== 'string') throw new Failure('tool_failed', 'Codex returned an unreadable sign-in answer.');
      loginId = result.loginId;
      const address = byCode ? result.verificationUrl : result.authUrl;
      if (typeof address !== 'string' || (byCode && typeof result.userCode !== 'string')) throw new Failure('tool_failed', 'Codex returned no sign-in address.');
      let url: URL;
      try { url = new URL(address); } catch { throw new Failure('tool_failed', 'Codex returned an invalid sign-in address.'); }
      if (url.protocol !== 'https:' || url.hostname !== 'auth.openai.com' || url.username || url.password) throw new Failure('tool_failed', 'Codex returned an unexpected sign-in host.');
      emit({ step: 'open_url', url: address, allowedHosts: ['auth.openai.com', '127.0.0.1'], expiresAt: progress.expiresAt,
        ...(byCode ? { userCode: result.userCode } : {}) });
      const remaining = Math.max(1, Date.parse(progress.expiresAt) - Date.now());
      const completed = await server.waitForNotification('account/login/completed', value => isObject(value) && value.loginId === loginId, { signal, timeoutMs: remaining });
      if (!isObject(completed) || completed.success !== true) throw new Failure('vendor_error', typeof (completed as any)?.error === 'string' ? (completed as any).error : 'Codex sign-in failed.');
      const account = normalizeAccount(await server.request('account/read', { refreshToken: false }, { signal }));
      signal.throwIfAborted();
      if (!account) throw this.rejection('Codex did not confirm a ChatGPT account after sign-in.');
      if ((await this.progress(id))?.stopReason) throw new Failure('in_use', 'Another sign-in took its place.');
      await this.finish(id, progress, { state: 'signed_in', account, checkedAt: now() });
      success = true; emit({ step: 'done', subscription: await this.get(id) }); return 0;
    } catch (error) {
      const pending = progress ? await this.progress(id) : undefined;
      let failure = safeFailure(error);
      if (pending?.attempt === progress?.attempt && pending?.stopReason) failure = new Failure('in_use', 'Another sign-in took its place.').result;
      else if (timeout.signal.aborted || (progress && Date.now() >= Date.parse(progress.expiresAt))) failure = new Failure('limit_reached', 'The sign-in ended after five minutes.').result;
      else if (this.signal?.aborted) failure = new Failure('vendor_error', 'The caller cancelled sign-in.').result;
      emit({ step: 'failed', error: failure });
      return this.signal?.aborted && failure.code !== 'in_use' ? 2 : 1;
    } finally {
      if (timer) clearTimeout(timer);
      if (server && !success) {
        if (loginId) await server.request('account/login/cancel', { loginId }, { timeoutMs: fixedWait(1000, this.env) }).catch(() => {});
        await server.request('account/logout', {}, { timeoutMs: fixedWait(1000, this.env) }).catch(() => {});
      }
      await server?.close();
      if (progress) await this.finish(id, progress, success ? undefined : { state: 'signed_out', checkedAt: now() });
    }
  }
  private async activeRuns(id: string, force: boolean): Promise<void> {
    const directory = join(this.state.directory, 'runs');
    const entries = await readdir(directory).catch((error: unknown) => { if (errno(error, 'ENOENT')) return []; throw error; });
    for (const entry of entries) {
      if (!entry.endsWith('.json')) continue;
      const file = join(directory, entry); const run = await readJson(file);
      if (!isObject(run) || run.subscriptionId !== id) continue;
      const owner = parseOwner(run.owner); const live = await ownerAlive(owner);
      if (live && !force) throw new Failure('in_use', 'A run uses this Subscription. Stop it first or use --force.');
      if (live) {
        try { process.kill(owner.pid, 'SIGTERM'); } catch (error) { if (!errno(error, 'ESRCH')) throw error; }
        const deadline = performance.now() + fixedWait(20000, this.env);
        while (await readJson(file) !== undefined && await ownerAlive(owner)) {
          if (performance.now() > deadline) throw new Failure('in_use', 'The active run did not stop.');
          await delay(fixedWait(50, this.env));
        }
      }
      if (!(await ownerAlive(owner))) {
        await this.killTool(run.tool === undefined ? undefined : parseOwner(run.tool));
        await rm(join(this.state.directory, 'tmp', entry.slice(0, -5)), { recursive: true, force: true });
        await missing(file);
      }
    }
  }
  async signOut(id: string, force = false): Promise<Subscription> {
    await this.get(id); await this.activeRuns(id, force);
    const progress = await this.reserve(id, 'sign_out'); let server: AppServer | undefined;
    try {
      server = await this.start(id, tool => this.setTool(id, progress, tool));
      await server.request('account/logout', {}, this.waitOptions());
      this.signal?.throwIfAborted();
      await this.finish(id, progress, { state: 'signed_out', checkedAt: now() });
      return this.get(id);
    } finally { await server?.close(); await this.finish(id, progress); }
  }
  async remove(id: string, force = false): Promise<void> {
    await this.get(id); await this.activeRuns(id, force);
    const progress = await this.reserve(id, 'remove');
    try {
      await this.state.withSubscriptionLock(id, async () => {
        await rm(this.file(id, 'home'), { recursive: true, force: true });
        await rm(this.file(id, 'chats'), { recursive: true, force: true });
        await missing(this.file(id, 'record.json'));
      }, this.env);
    } finally { await this.finish(id, progress); }
  }
}
