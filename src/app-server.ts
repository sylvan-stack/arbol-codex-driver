import { spawn } from 'node:child_process';
import type { ChildProcessWithoutNullStreams } from 'node:child_process';
import { StringDecoder } from 'node:string_decoder';
import { homedir } from 'node:os';
import { realpath } from 'node:fs/promises';
import { isAbsolute, join, resolve } from 'node:path';
import { buildIdentity } from './build.js';
import { cleanEnvironment } from './environment.js';
import { Failure, errno, safeText } from './errors.js';
import { isObject } from './settings.js';
import { collectProcessGroups, endProcessGroups } from './process-groups.js';
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
  onServerRequest?: (method: string, params: unknown) => unknown;
  launchIdentityPath?: string;
}
interface Pending {
  resolve(value: unknown): void;
  reject(error: Error): void;
  dispose(): void;
}
export interface Notification { method: string; params: unknown }
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
  private notificationWaiter: Pending | undefined;
  private logTail = '';
  effectiveConfig: Record<string, unknown> = {};
  toolVersion: string | undefined;
  private failure: Error | undefined;
  private closing: Promise<void> | undefined;
  private ending: Promise<void> | undefined;
  private closeResolve!: () => void;
  private readonly closed: Promise<void>;
  private readonly decoder = new StringDecoder('utf8');
  private buffer = '';
  private removeAbort: (() => void) | undefined;
  private readonly groups = new Map<number, Owner>();

  private constructor(private readonly child: ChildProcessWithoutNullStreams, owner: Owner, private readonly timeoutMs: number, private readonly cleanupGraceMs: number,
    private readonly onServerRequest?: AppServerOptions['onServerRequest']) {
    this.ownerRecord = owner;
    this.groups.set(owner.pid, owner);
    this.closed = new Promise<void>(resolve => { this.closeResolve = resolve; });
    child.stdout.on('data', (chunk: Buffer) => this.consume(this.decoder.write(chunk)));
    child.stdout.once('end', () => {
      this.consume(this.decoder.end());
      if (this.buffer.trim()) this.fail(new Failure('tool_failed', 'codex returned an incomplete app-server message.'));
      this.fail(new Failure('tool_failed', 'The codex app-server output ended.', { detail: { basis: 'fields', excerpt: this.logTail } }));
    });
    // Keep only the bounded in-memory tail for a failed run's diagnostic.
    child.stderr.setEncoding('utf8');
    child.stderr.on('data', (chunk: string) => { this.logTail = safeText(this.logTail + chunk, [], 64 * 1024); });
    child.stdin.on('error', () => this.fail(new Failure('tool_failed', 'Cannot send a request to codex.')));
    child.once('error', () => this.fail(new Failure('tool_failed', 'Cannot start the codex app-server.')));
    child.once('exit', code => {
      this.fail(new Failure('tool_failed', 'The codex app-server exited.', { detail: { basis: 'fields', ...(code === null ? {} : { toolExit: code }), excerpt: this.logTail } }));
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
    const launcher = options.launchIdentityPath && process.platform !== 'win32';
    const child = spawn(launcher ? '/bin/sh' : options.toolPath, launcher ? ['-c',
      'umask 077; ledger="$1.write"; { printf "%s\\n" "$$"; TZ=UTC LC_ALL=C /bin/ps -p "$$" -o lstart=; } > "$ledger" && /bin/mv -f "$ledger" "$1" || exit 1; exec "$2" app-server',
      'arbol-codex-launch', options.launchIdentityPath!, options.toolPath] : ['app-server'], {
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
    const server = new AppServer(child, { pid: child.pid, startedAt: new Date().toISOString() }, requestTimeoutMs, cleanupGraceMs, options.onServerRequest);
    const abort = (): void => {
      const stoppedAt = performance.now();
      server.fail(aborted());
      void server.end(stoppedAt + fixedWait(15000, options.env), stoppedAt + fixedWait(2000, options.env)).catch(() => {});
    };
    if (options.signal) {
      options.signal.addEventListener('abort', abort, { once: true });
      server.removeAbort = () => options.signal?.removeEventListener('abort', abort);
    }
    try {
      const owner = await processOwner(child.pid);
      if (!owner) throw new Failure('tool_failed', 'Cannot identify the codex app-server process.');
      server.ownerRecord = owner;
      server.groups.set(owner.pid, owner);
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
      if (isObject(answer) && typeof answer.userAgent === 'string') server.toolVersion = answer.userAgent.match(/^[^/]+\/([^ ]+)/)?.[1];
      server.send({ method: 'initialized' });
      const configuration = await server.request('config/read', {});
      validateDriverConfig(configuration);
      server.effectiveConfig = (configuration as { config: Record<string, unknown> }).config;
      // The caller owns the lifecycle after startup. In particular, sign-in
      // cancellation must send account/login/cancel before stopping the tool.
      server.removeAbort?.();
      server.removeAbort = undefined;
      return server;
    } catch (error) {
      await server.end();
      throw error;
    }
  }

  /** Lossless ordered inference notifications, including those before turn/start answers. */
  takeNotifications(): Notification[] { return this.notifications.splice(0); }

  nextNotification(options: WaitOptions = {}): Promise<Notification> {
    if (options.signal?.aborted) return Promise.reject(aborted());
    const early = this.notifications.shift();
    if (early) return Promise.resolve(early);
    if (this.failure) return Promise.reject(this.failure);
    if (this.notificationWaiter) return Promise.reject(new Failure('internal', 'An app-server notification reader is already waiting.'));
    return new Promise<Notification>((resolve, reject) => {
      const abort = (): void => { this.notificationWaiter = undefined; dispose(); reject(aborted()); };
      const timer = options.timeoutMs === undefined ? undefined : setTimeout(() => {
        this.notificationWaiter = undefined; dispose(); reject(new Failure('tool_failed', 'Timed out waiting for codex output.'));
      }, options.timeoutMs);
      const dispose = (): void => { clearTimeout(timer); options.signal?.removeEventListener('abort', abort); };
      this.notificationWaiter = { resolve: value => resolve(value as Notification), reject, dispose };
      options.signal?.addEventListener('abort', abort, { once: true });
    });
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
        void this.end().catch(() => {});
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
    let newline: number;
    while ((newline = this.buffer.indexOf('\n')) >= 0) {
      const line = this.buffer.slice(0, newline);
      this.buffer = this.buffer.slice(newline + 1);
      if (Buffer.byteLength(line) > 4 * 1024 * 1024) { this.oversized(); return; }
      if (!line.trim()) continue;
      let message: unknown;
      try { message = JSON.parse(line) as unknown; }
      catch { this.malformed(); return; }
      if (!isObject(message)) { this.malformed(); return; }
      if (typeof message.method === 'string') {
        if (message.id !== undefined) {
          // Account operations have no supported server requests. Always answer
          // an unknown request so it cannot strand the vendor tool.
          const result = this.onServerRequest?.(message.method, message.params);
          this.send(result === undefined ? { id: message.id, error: { code: -32601, message: 'Method not supported by the Driver.' } } : { id: message.id, result });
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
    if (Buffer.byteLength(this.buffer) > 4 * 1024 * 1024) this.oversized();
  }

  private notify(method: string, params: unknown): void {
    if (this.notificationWaiter) {
      const waiter = this.notificationWaiter; this.notificationWaiter = undefined;
      waiter.dispose(); waiter.resolve({ method, params }); return;
    }
    for (const watcher of this.watchers) {
      if (watcher.method !== method) continue;
      let matches: boolean;
      try { matches = watcher.predicate(params); }
      catch (error) { this.watchers.delete(watcher); watcher.dispose(); watcher.reject(error as Error); continue; }
      if (matches) { this.watchers.delete(watcher); watcher.dispose(); watcher.resolve(params); return; }
    }
    this.notifications.push({ method, params });
  }

  private malformed(): void {
    this.fail(new Failure('tool_failed', 'codex returned a malformed app-server message.'));
    void this.close().catch(() => {});
  }
  private oversized(): void {
    this.fail(new Failure('tool_failed', 'codex returned an oversized app-server message.'));
    void this.close().catch(() => {});
  }
  private fail(error: Error): void {
    this.failure ??= error;
    for (const pending of this.pending.values()) { pending.dispose(); pending.reject(this.failure); }
    this.pending.clear();
    for (const watcher of this.watchers) { watcher.dispose(); watcher.reject(this.failure); }
    this.watchers.clear();
    if (this.notificationWaiter) {
      const waiter = this.notificationWaiter; this.notificationWaiter = undefined; waiter.dispose(); waiter.reject(this.failure);
    }
  }
  private killGroup(signal: NodeJS.Signals): void {
    try {
      if (process.platform === 'win32') this.child.kill(signal);
      else process.kill(-this.owner.pid, signal);
    } catch (error) { if (!errno(error, 'ESRCH')) this.failure ??= new Failure('tool_failed', 'Cannot stop the codex app-server.'); }
  }
  async captureProcessGroups(): Promise<Owner[]> {
    for (const owner of await collectProcessGroups(this.owner)) this.groups.set(owner.pid, owner);
    return [...this.groups.values()];
  }
  close(deadline = performance.now() + fixedWait(10000), forceAt?: number): Promise<void> {
    if (this.closing) return this.closing;
    this.fail(new Failure('tool_failed', 'The codex app-server was stopped.'));
    this.removeAbort?.();
    this.closing = (async () => {
      let cleanupError: unknown;
      await this.captureProcessGroups().catch(error => { cleanupError = error; });
      if (!this.child.stdin.writableEnded) this.child.stdin.end();
      const survivors = await endProcessGroups([...this.groups.values()], deadline, forceAt).catch(error => {
        cleanupError ??= error; this.killGroup('SIGKILL'); return [...this.groups.values()];
      });
      // Detaching does not detach the pipe handles. Bound cleanup even when a
      // grandchild escapes the group and retains one of the inherited pipes.
      this.child.stdin.destroy(); this.child.stdout.destroy(); this.child.stderr.destroy();
      let finalTimer: ReturnType<typeof setTimeout> | undefined;
      await Promise.race([this.closed, new Promise<void>(resolve => { finalTimer = setTimeout(resolve, this.cleanupGraceMs); })]);
      if (finalTimer) clearTimeout(finalTimer);
      if (cleanupError) throw cleanupError;
      if (survivors.length) throw new Failure('tool_failed', 'Some codex processes could not be ended.', { detail: { basis: 'fields', excerpt: JSON.stringify(survivors) } });
    })();
    return this.closing;
  }

  /** Normal run completion lets the app-server clean up its commands on stdin EOF. */
  end(deadline = performance.now() + fixedWait(15000), forceAt?: number): Promise<void> {
    if (this.closing) return this.closing;
    if (this.ending) return this.ending;
    this.ending = (async () => {
      let captureError: unknown;
      await this.captureProcessGroups().catch(error => { captureError = error; });
      if (!this.child.stdin.writableEnded) this.child.stdin.end();
      let timer: ReturnType<typeof setTimeout> | undefined;
      const eofDeadline = Math.min(deadline, forceAt ?? performance.now() + fixedWait(2000));
      await Promise.race([this.closed, new Promise<void>(resolve => { timer = setTimeout(resolve, Math.max(1, eofDeadline - performance.now())); })]);
      clearTimeout(timer);
      await this.close(deadline, forceAt);
      if (captureError) throw captureError;
    })();
    return this.ending;
  }
}
