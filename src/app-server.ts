import { spawn } from 'node:child_process';
import type { ChildProcessWithoutNullStreams } from 'node:child_process';
import { StringDecoder } from 'node:string_decoder';
import { homedir } from 'node:os';
import { realpath } from 'node:fs/promises';
import { isAbsolute, join, resolve } from 'node:path';
import { buildIdentity } from './build.js';
import { cleanEnvironment } from './environment.js';
import { Failure, errno } from './errors.js';
import { isObject } from './settings.js';
import { atomicWrite, fixedWait, privateDirectory, processOwner } from './state.js';
import type { Owner } from './state.js';
import type { ProcessEnv } from './types.js';

export const DRIVER_CONFIG = 'check_for_update_on_startup = false\nweb_search = "live"\ncli_auth_credentials_store = "file"\n\n[analytics]\nenabled = false\n\n[features]\nmemories = false\n';

export async function writeDriverConfig(home: string): Promise<void> {
  await privateDirectory(home);
  // This file belongs to the Driver. Never inspect or copy the tool's login.
  await atomicWrite(join(home, 'config.toml'), DRIVER_CONFIG);
}

export function validateDriverConfig(value: unknown): void {
  const config = isObject(value) && isObject(value.config) ? value.config : undefined;
  if (!config || config.check_for_update_on_startup !== false || config.web_search !== 'live' ||
      config.cli_auth_credentials_store !== 'file' || !isObject(config.analytics) || config.analytics.enabled !== false ||
      !isObject(config.features) || config.features.memories !== false) {
    throw new Failure('tool_failed', 'codex did not apply the Driver configuration.');
  }
}

export interface WaitOptions { signal?: AbortSignal; timeoutMs?: number }
export interface AppServerOptions {
  toolPath: string;
  home: string;
  env: ProcessEnv;
  cwd?: string;
  signal?: AbortSignal;
  requestTimeoutMs?: number;
  onSpawn?: (owner: Owner) => Promise<void> | void;
}
interface Pending {
  resolve(value: unknown): void;
  reject(error: Error): void;
  dispose(): void;
}
interface Notification { method: string; params: unknown }
interface Watcher extends Pending { method: string; predicate: (params: unknown) => boolean }

function aborted(): Failure { return new Failure('tool_failed', 'The codex operation was cancelled.'); }
function rpcFailure(error: Record<string, unknown>): Failure {
  const message = error.message as string;
  const data = isObject(error.data) ? error.data : undefined;
  const status = typeof data?.httpStatusCode === 'number' ? data.httpStatusCode :
    typeof error.code === 'number' && [401, 403].includes(error.code) ? error.code : undefined;
  const structuredAuth = status === 401 || status === 403 || error.code === 'unauthorized' ||
    error.code === 'credential_rejected' || data?.codexErrorInfo === 'unauthorized';
  const wordingAuth = /codex account authentication required to read (?:rate limits|token usage)|not logged in|logged out|codex login|invalid api key|missing credentials|please login|please log in|chatgpt login expired/i.test(message);
  const detail: NonNullable<Failure['result']['detail']> = { basis: !structuredAuth && wordingAuth ? 'wording' : 'fields' };
  if (status !== undefined) detail.vendorStatus = status;
  if (typeof error.code === 'string' || typeof error.code === 'number') detail.vendorCode = String(error.code);
  return new Failure(structuredAuth || wordingAuth ? 'credential_rejected' : 'tool_failed', message,
    { detail, ...(structuredAuth || wordingAuth ? { remedy: 'Sign in again.' } : {}) });
}

/** One JSONL app-server in the home of one Subscription. */
export class AppServer {
  private ownerRecord: Owner;
  get owner(): Owner { return this.ownerRecord; }
  private nextId = 1;
  private readonly pending = new Map<number, Pending>();
  private readonly notifications: Notification[] = [];
  private readonly watchers = new Set<Watcher>();
  private failure: Error | undefined;
  private closing: Promise<void> | undefined;
  private closeResolve!: () => void;
  private readonly closed: Promise<void>;
  private readonly decoder = new StringDecoder('utf8');
  private buffer = '';
  private removeAbort: (() => void) | undefined;

  private constructor(private readonly child: ChildProcessWithoutNullStreams, owner: Owner, private readonly timeoutMs: number, private readonly cleanupGraceMs: number) {
    this.ownerRecord = owner;
    this.closed = new Promise<void>(resolve => { this.closeResolve = resolve; });
    child.stdout.on('data', (chunk: Buffer) => this.consume(this.decoder.write(chunk)));
    child.stdout.once('end', () => {
      this.consume(this.decoder.end());
      if (this.buffer.trim()) this.fail(new Failure('tool_failed', 'codex returned an incomplete app-server message.'));
    });
    // Drain stderr but never persist or print arbitrary tool output: it may
    // contain private configuration or authentication diagnostics.
    child.stderr.resume();
    child.stdin.on('error', () => this.fail(new Failure('tool_failed', 'Cannot send a request to codex.')));
    child.once('error', () => this.fail(new Failure('tool_failed', 'Cannot start the codex app-server.')));
    child.once('exit', code => {
      this.fail(new Failure('tool_failed', 'The codex app-server exited.', code === null ? {} : { detail: { basis: 'fields', toolExit: code } }));
      // Wrappers may leave descendants holding pipes open after the parent exits.
      this.killGroup('SIGKILL');
    });
    child.once('close', () => { this.removeAbort?.(); this.closeResolve(); });
  }

  static async start(options: AppServerOptions): Promise<AppServer> {
    if (options.signal?.aborted) throw aborted();
    const cleanupGraceMs = fixedWait(500, options.env);
    const requestTimeoutMs = options.requestTimeoutMs ?? 30000;
    if (!Number.isFinite(requestTimeoutMs) || requestTimeoutMs <= 0) {
      throw new Failure('invalid_input', 'The app-server request timeout must be a positive finite number.');
    }
    const home = resolve(options.home);
    await writeDriverConfig(home);
    const identity = await buildIdentity();
    if (options.signal?.aborted) throw aborted();
    const child = spawn(options.toolPath, ['app-server'], {
      cwd: options.cwd ?? home,
      env: cleanEnvironment(options.env, options.env.HOME ?? homedir(), home),
      detached: process.platform !== 'win32',
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    if (!child.pid) {
      await new Promise<void>(resolve => { child.once('error', () => resolve()); child.once('close', () => resolve()); });
      throw new Failure('tool_failed', 'Cannot start the codex app-server.');
    }
    // Install listeners before the asynchronous owner lookup: even a wrapper
    // that exits immediately must be drained and its process group stopped.
    const server = new AppServer(child, { pid: child.pid, startedAt: new Date().toISOString() }, requestTimeoutMs, cleanupGraceMs);
    const abort = (): void => { server.fail(aborted()); void server.close(); };
    if (options.signal) {
      options.signal.addEventListener('abort', abort, { once: true });
      server.removeAbort = () => options.signal?.removeEventListener('abort', abort);
    }
    try {
      const owner = await processOwner(child.pid);
      if (!owner) throw new Failure('tool_failed', 'Cannot identify the codex app-server process.');
      server.ownerRecord = owner;
      await options.onSpawn?.(owner);
      if (options.signal?.aborted) throw aborted();
      const answer = await server.request('initialize', { clientInfo: { name: 'arbol-codex-driver', version: identity.version } });
      let sameHome = false;
      if (isObject(answer) && typeof answer.codexHome === 'string' && isAbsolute(answer.codexHome)) {
        sameHome = await Promise.all([realpath(answer.codexHome), realpath(home)]).then(([actual, expected]) => actual === expected, () => false);
      }
      if (!sameHome) {
        throw new Failure('tool_failed', 'codex opened a different Subscription home.');
      }
      server.send({ method: 'initialized' });
      validateDriverConfig(await server.request('config/read', {}));
      // The caller owns the lifecycle after startup. In particular, sign-in
      // cancellation must send account/login/cancel before stopping the tool.
      server.removeAbort?.();
      server.removeAbort = undefined;
      return server;
    } catch (error) {
      await server.close();
      throw error;
    }
  }

  request<T = unknown>(method: string, params: unknown, options: WaitOptions = {}): Promise<T> {
    if (this.failure) return Promise.reject(this.failure);
    if (options.signal?.aborted) return Promise.reject(aborted());
    const id = this.nextId++;
    return new Promise<T>((resolve, reject) => {
      const abort = (): void => { finish(aborted()); };
      const timer = setTimeout(() => {
        const error = new Failure('tool_failed', `codex did not answer ${method} within the request timeout.`);
        this.fail(error);
        void this.close();
      }, options.timeoutMs ?? this.timeoutMs);
      const dispose = (): void => { clearTimeout(timer); options.signal?.removeEventListener('abort', abort); };
      const finish = (error: Error): void => { this.pending.delete(id); dispose(); reject(error); };
      this.pending.set(id, { resolve: value => resolve(value as T), reject, dispose });
      options.signal?.addEventListener('abort', abort, { once: true });
      try { this.send({ id, method, params }); }
      catch (error) { finish(error as Error); }
    });
  }

  waitForNotification<T = unknown>(method: string, predicate: (params: T) => boolean = () => true, options: WaitOptions = {}): Promise<T> {
    if (options.signal?.aborted) return Promise.reject(aborted());
    // Keep unmatched notifications: a login completion often arrives in the
    // same stdout chunk as account/login/start, before its caller can wait.
    const index = this.notifications.findIndex(item => item.method === method && predicate(item.params as T));
    if (index >= 0) return Promise.resolve(this.notifications.splice(index, 1)[0]!.params as T);
    if (this.failure) return Promise.reject(this.failure);
    return new Promise<T>((resolve, reject) => {
      let watcher: Watcher;
      const abort = (): void => { this.watchers.delete(watcher); watcher.dispose(); reject(aborted()); };
      const timer = setTimeout(() => {
        this.watchers.delete(watcher);
        watcher.dispose();
        reject(new Failure('tool_failed', `Timed out waiting for codex ${method}.`));
      }, options.timeoutMs ?? this.timeoutMs);
      watcher = {
        method, predicate: params => predicate(params as T), resolve: value => resolve(value as T), reject,
        dispose: () => { clearTimeout(timer); options.signal?.removeEventListener('abort', abort); },
      };
      this.watchers.add(watcher);
      options.signal?.addEventListener('abort', abort, { once: true });
    });
  }

  private send(message: unknown): void {
    if (this.failure) throw this.failure;
    this.child.stdin.write(JSON.stringify(message) + '\n');
  }

  private consume(chunk: string): void {
    if (this.failure) return;
    this.buffer += chunk;
    if (Buffer.byteLength(this.buffer) > 4 * 1024 * 1024) {
      this.fail(new Failure('tool_failed', 'codex returned an oversized app-server message.'));
      void this.close();
      return;
    }
    let newline: number;
    while ((newline = this.buffer.indexOf('\n')) >= 0) {
      const line = this.buffer.slice(0, newline);
      this.buffer = this.buffer.slice(newline + 1);
      if (!line.trim()) continue;
      let message: unknown;
      try { message = JSON.parse(line) as unknown; }
      catch { this.malformed(); return; }
      if (!isObject(message)) { this.malformed(); return; }
      if (typeof message.method === 'string') {
        if (message.id !== undefined) {
          // Account operations have no supported server requests. Always answer
          // an unknown request so it cannot strand the vendor tool.
          this.send({ id: message.id, error: { code: -32601, message: 'Method not supported by the Driver.' } });
        } else this.notify(message.method, message.params);
      } else if (typeof message.id === 'number' && (('result' in message) !== ('error' in message))) {
        const pending = this.pending.get(message.id);
        if (!pending) continue;
        this.pending.delete(message.id);
        pending.dispose();
        if ('error' in message) {
          const error = message.error;
          if (!isObject(error) || typeof error.message !== 'string') { pending.reject(new Failure('tool_failed', 'codex returned a malformed error.')); continue; }
          pending.reject(rpcFailure(error));
        } else pending.resolve(message.result);
      } else { this.malformed(); return; }
    }
  }

  private notify(method: string, params: unknown): void {
    for (const watcher of this.watchers) {
      if (watcher.method !== method) continue;
      let matches: boolean;
      try { matches = watcher.predicate(params); }
      catch (error) { this.watchers.delete(watcher); watcher.dispose(); watcher.reject(error as Error); continue; }
      if (matches) { this.watchers.delete(watcher); watcher.dispose(); watcher.resolve(params); return; }
    }
    this.notifications.push({ method, params });
    if (this.notifications.length > 256) this.notifications.shift();
  }

  private malformed(): void {
    this.fail(new Failure('tool_failed', 'codex returned a malformed app-server message.'));
    void this.close();
  }
  private fail(error: Error): void {
    this.failure ??= error;
    for (const pending of this.pending.values()) { pending.dispose(); pending.reject(this.failure); }
    this.pending.clear();
    for (const watcher of this.watchers) { watcher.dispose(); watcher.reject(this.failure); }
    this.watchers.clear();
  }
  private killGroup(signal: NodeJS.Signals): void {
    try {
      if (process.platform === 'win32') this.child.kill(signal);
      else process.kill(-this.owner.pid, signal);
    } catch (error) { if (!errno(error, 'ESRCH')) this.failure ??= new Failure('tool_failed', 'Cannot stop the codex app-server.'); }
  }
  close(): Promise<void> {
    if (this.closing) return this.closing;
    this.fail(new Failure('tool_failed', 'The codex app-server was stopped.'));
    this.removeAbort?.();
    this.closing = (async () => {
      this.killGroup('SIGTERM');
      let timer: ReturnType<typeof setTimeout> | undefined;
      await Promise.race([this.closed, new Promise<void>(resolve => { timer = setTimeout(resolve, this.cleanupGraceMs); })]);
      if (timer) clearTimeout(timer);
      this.killGroup('SIGKILL');
      // Detaching does not detach the pipe handles. Bound cleanup even when a
      // grandchild escapes the group and retains one of the inherited pipes.
      this.child.stdin.destroy(); this.child.stdout.destroy(); this.child.stderr.destroy();
      let finalTimer: ReturnType<typeof setTimeout> | undefined;
      await Promise.race([this.closed, new Promise<void>(resolve => { finalTimer = setTimeout(resolve, this.cleanupGraceMs); })]);
      if (finalTimer) clearTimeout(finalTimer);
    })();
    return this.closing;
  }
}
