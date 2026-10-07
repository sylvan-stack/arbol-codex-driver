import { Failure } from './errors.js';
import type { DriverError } from './errors.js';
import { isObject } from './settings.js';

export interface RunUsage {
  model?: string;
  inputTokens?: number;
  cachedInputTokens?: number;
  outputTokens?: number;
  reasoningTokens?: number;
}
export interface OpenCall { name: string; type: string }
interface Call extends OpenCall { output: string; outputCut: boolean }
const resultLimit = 200 * 1024;
const protocolFailure = (): Failure => new Failure('tool_failed', 'codex returned a malformed run notification.');
const number = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value) && value >= 0;

function prefix(text: string, limit: number): { text: string; cut: boolean } {
  const bytes = Buffer.from(text);
  if (bytes.length <= limit) return { text, cut: false };
  let end = limit;
  while (end > 0 && (bytes[end]! & 0xc0) === 0x80) end--;
  return { text: bytes.subarray(0, end).toString('utf8'), cut: true };
}

/** Bound every result shape by its UTF-8 representation, retaining small results. */
export function truncateResult(result: unknown): { result: unknown; truncated?: true } {
  const text = typeof result === 'string' ? result : JSON.stringify(result);
  if (text === undefined) return { result };
  const bounded = prefix(text, resultLimit);
  return bounded.cut ? { result: bounded.text, truncated: true } : { result };
}

// Tokenize only to undo a vendor launcher; never execute or expand its content.
function shellWords(text: string): string[] | undefined {
  const words: string[] = [];
  let word = '', quote = '', present = false;
  for (let i = 0; i < text.length; i++) {
    const char = text[i]!;
    if (quote === "'") {
      if (char === "'") quote = ''; else word += char;
    } else if (char === '"') {
      quote = quote === '"' ? '' : '"'; present = true;
    } else if (!quote && char === "'") {
      quote = "'"; present = true;
    } else if (char === '\\' && (quote === '' || /[$`"\\\n]/.test(text[i + 1] ?? ''))) {
      if (++i === text.length) return undefined;
      if (text[i] !== '\n') word += text[i];
      present = true;
    } else if (!quote && /\s/.test(char)) {
      if (present) { words.push(word); word = ''; present = false; }
    } else { word += char; present = true; }
  }
  if (quote) return undefined;
  if (present) words.push(word);
  return words;
}

export function plainCommand(command: string): string {
  const words = shellWords(command);
  if (words?.length === 3 && /(?:^|\/)(?:sh|bash|zsh|dash|ksh|fish)$/.test(words[0]!) && /^-[il]*c[il]*$/.test(words[1]!)) return words[2]!;
  return command;
}

function failure(error: unknown): DriverError {
  const message = isObject(error) && typeof error.message === 'string' ? error.message : 'codex failed the turn.';
  return new Failure('vendor_error', message).result;
}

/** Notification mapping only: the caller owns startup, cancellation and final cleanup. */
export class RunEvents {
  private totals: RunUsage;
  private lastTotal: string | undefined;
  private foreignNotice = false;
  private readonly calls = new Map<string, Call>();
  private readonly closed = new Set<string>();
  private readonly interrupted = new Set<string>();
  private readonly completedItems = new Set<string>();
  private readonly agents = new Map<string, { path?: string; active: boolean; mapper?: RunEvents }>();
  outputProduced = false;
  outcome: 'completed' | 'failed' | 'interrupted' | undefined;
  error: DriverError | undefined;

  constructor(readonly threadId: string, readonly turnId: string, model: string,
    private readonly emit: (type: string, data: Record<string, unknown>) => void) {
    this.totals = { model };
  }
  get usage(): RunUsage { return { ...this.totals }; }
  get openCalls(): ReadonlyMap<string, OpenCall> { return this.calls; }
  get unfinishedCalls(): string[] { return [...this.interrupted, ...this.calls.keys(),
    ...[...this.agents.values()].flatMap(agent => agent.mapper?.unfinishedCalls ?? [])]; }
  knowsThread(threadId: string): boolean {
    return this.threadId === threadId || this.agents.has(threadId) ||
      [...this.agents.values()].some(agent => agent.mapper?.knowsThread(threadId));
  }
  get activeTurns(): Array<{ threadId: string; turnId: string }> {
    return [...(this.outcome === undefined ? [{ threadId: this.threadId, turnId: this.turnId }] : []),
      ...[...this.agents.values()].flatMap(agent => agent.mapper?.activeTurns ?? [])];
  }
  get waitingForWork(): boolean {
    return [...this.calls.values()].some(call => call.type === 'commandExecution') ||
      [...this.agents.values()].some(agent => agent.active || agent.mapper?.waitingForWork);
  }
  get hasActiveAgents(): boolean {
    return [...this.agents.values()].some(agent => agent.active || agent.mapper?.hasActiveAgents);
  }

  closeOpenCalls(message = 'The run ended before the tool call finished.'): void {
    for (const agent of this.agents.values()) agent.mapper?.closeOpenCalls(message);
    for (const callId of this.calls.keys()) {
      this.interrupted.add(callId); this.closed.add(callId);
      this.emit('tool_finished', { callId, ok: false, error: message, interrupted: true });
    }
    this.calls.clear();
  }

  consume(method: string, value: unknown): void {
    if (!isObject(value)) {
      if (method.startsWith('item/') || ['turn/completed', 'thread/tokenUsage/updated', 'error', 'warning', 'model/rerouted', 'deprecationNotice'].includes(method)) throw protocolFailure();
      return;
    }
    const params = value;
    // Check identity even for notifications whose content otherwise needs no event.
    if (typeof params.threadId === 'string' && params.threadId !== this.threadId) {
      const ancestor = [...this.agents.values()].find(agent => agent.mapper?.knowsThread(params.threadId as string));
      if (ancestor?.mapper && !this.agents.has(params.threadId)) { ancestor.mapper.consume(method, params); return; }
      const agent = this.agents.get(params.threadId);
      if (agent) {
        const turnId = params.turnId ?? (isObject(params.turn) ? params.turn.id : undefined);
        if (typeof turnId === 'string') {
          if (!agent.mapper || method === 'turn/started' && agent.mapper.outcome !== undefined) {
            agent.mapper = new RunEvents(params.threadId, turnId, this.totals.model ?? '',
              (type, data) => this.emit(type, { parentCallId: params.threadId, ...data }));
            agent.active = true;
          }
          agent.mapper.consume(method, params);
          if (method === 'turn/completed') agent.active = false;
        }
        return;
      }
      if (!this.foreignNotice) {
        this.foreignNotice = true;
        this.emit('notice', { code: 'foreign_thread', message: 'A notification for another codex thread was ignored.' });
      }
      return;
    }
    const turn = isObject(params.turn) ? params.turn : undefined;
    const turnId = params.turnId ?? turn?.id;
    if (params.threadId === this.threadId && turnId !== undefined && turnId !== null && turnId !== this.turnId) {
      throw new Failure('tool_failed', 'codex sent a notification for another turn of the run thread.');
    }
    switch (method) {
      case 'item/agentMessage/delta':
      case 'item/reasoning/summaryTextDelta':
        this.identity(params);
        if (typeof params.delta !== 'string') throw protocolFailure();
        this.text(method === 'item/agentMessage/delta' ? 'text_delta' : 'thinking_delta', params.delta);
        break;
      case 'item/started':
      case 'item/completed': {
        this.identity(params);
        if (!isObject(params.item) || typeof params.item.type !== 'string' || typeof params.item.id !== 'string' || !params.item.id) throw protocolFailure();
        const item = params.item;
        if (item.type === 'subAgentActivity') { this.agentActivity(item); break; }
        if (item.type === 'userMessage' || item.type === 'hookPrompt' || item.type === 'contextCompaction' || item.type === 'functionCallOutput') break;
        if (item.type === 'agentMessage' || item.type === 'reasoning') {
          if (method === 'item/started' || this.completedItems.has(item.id as string)) break;
          if (item.type === 'agentMessage') {
            if (typeof item.text !== 'string') throw protocolFailure();
            this.text('text', item.text);
          } else {
            const summary = item.summary ?? [];
            if (!Array.isArray(summary) || !summary.every(part => typeof part === 'string')) throw protocolFailure();
            this.text('thinking', summary.join('\n\n'));
          }
          this.completedItems.add(item.id as string);
        } else if (method === 'item/started') this.startCall(item);
        else this.finishCall(item);
        break;
      }
      case 'item/commandExecution/outputDelta': {
        this.identity(params);
        if (typeof params.itemId !== 'string' || typeof params.delta !== 'string') throw protocolFailure();
        const call = this.calls.get(params.itemId);
        if (!call || call.type !== 'commandExecution') throw protocolFailure();
        this.emit('tool_output_delta', { callId: params.itemId, text: params.delta });
        if (!call.outputCut) {
          const bounded = prefix(call.output + params.delta, resultLimit);
          call.output = bounded.text; call.outputCut = bounded.cut;
        }
        break;
      }
      case 'thread/tokenUsage/updated': {
        this.identity(params);
        if (!isObject(params.tokenUsage) || !isObject(params.tokenUsage.last)) throw protocolFailure();
        const { last, total } = params.tokenUsage;
        // A replayed usage notification repeats both total and last. The total is
        // a deduplication marker only; it may contain earlier turns' usage.
        const marker = isObject(total) ? JSON.stringify(['totalTokens', 'inputTokens', 'cachedInputTokens', 'outputTokens', 'reasoningOutputTokens'].map(key => total[key])) : undefined;
        if (marker === undefined || marker !== this.lastTotal) {
          for (const [vendor, key] of [['inputTokens', 'inputTokens'], ['cachedInputTokens', 'cachedInputTokens'],
            ['outputTokens', 'outputTokens'], ['reasoningOutputTokens', 'reasoningTokens']] as const) {
            if (number(last[vendor])) this.totals[key] = (this.totals[key] ?? 0) + last[vendor];
          }
          this.lastTotal = marker;
        }
        this.emit('usage', { usage: this.usage });
        break;
      }
      case 'model/rerouted':
        this.identity(params);
        if (typeof params.toModel !== 'string' || !params.toModel) throw protocolFailure();
        this.totals.model = params.toModel;
        this.emit('notice', { code: 'model_rerouted', message: `codex rerouted the turn to ${params.toModel}${typeof params.reason === 'string' ? ` (${params.reason})` : ''}.` });
        this.emit('usage', { usage: this.usage });
        break;
      case 'warning':
        if (typeof params.message !== 'string') throw protocolFailure();
        this.emit('notice', { code: 'warning', message: params.message });
        break;
      case 'deprecationNotice':
        if (typeof params.summary !== 'string') throw protocolFailure();
        this.emit('notice', { code: 'deprecation', message: params.summary + (typeof params.details === 'string' && params.details ? '\n' + params.details : '') });
        break;
      case 'error':
        this.identity(params);
        if (!isObject(params.error) || typeof params.error.message !== 'string' || typeof params.willRetry !== 'boolean') throw protocolFailure();
        if (params.willRetry) this.emit('notice', { code: 'retrying', message: params.error.message });
        else this.error = failure(params.error);
        break;
      case 'turn/completed':
        this.identity(params, turn?.id);
        if (!turn || !['completed', 'failed', 'interrupted'].includes(String(turn.status)) || this.outcome !== undefined) throw protocolFailure();
        if (turn.status === 'failed' || turn.error !== null && turn.error !== undefined || this.error) {
          this.outcome = 'failed'; this.error = turn.error ? failure(turn.error) : this.error ?? failure(undefined);
        } else this.outcome = turn.status as 'completed' | 'interrupted';
        break;
    }
  }

  private identity(params: Record<string, unknown>, turnId: unknown = params.turnId): void {
    if (params.threadId !== this.threadId || turnId !== this.turnId) throw protocolFailure();
  }
  private text(type: string, text: string): void {
    if (!text) return;
    this.outputProduced = true; this.emit(type, { text });
  }
  private startCall(item: Record<string, unknown>): void {
    const callId = item.id as string, type = item.type as string;
    if (this.calls.has(callId) || this.closed.has(callId)) throw protocolFailure();
    let name = type, input: unknown = item;
    if (type === 'commandExecution') {
      if (typeof item.command !== 'string') throw protocolFailure();
      name = 'shell';
      input = { command: plainCommand(item.command), ...(typeof item.cwd === 'string' ? { cwd: item.cwd } : {}) };
    } else if (type === 'collabAgentToolCall') {
      if (typeof item.tool !== 'string') throw protocolFailure();
      name = item.tool;
    } else if (type === 'fileChange') {
      if (!Array.isArray(item.changes)) throw protocolFailure();
      name = 'apply_patch';
      input = item.changes.map(change => {
        if (!isObject(change) || typeof change.path !== 'string' || typeof change.diff !== 'string' || !isObject(change.kind) || typeof change.kind.type !== 'string') throw protocolFailure();
        return { path: change.path, kind: change.kind, content: change.diff };
      });
    }
    this.calls.set(callId, { name, type, output: '', outputCut: false });
    this.outputProduced = true;
    this.emit('tool_started', { callId, name, input });
  }
  private agentActivity(item: Record<string, unknown>): void {
    if (typeof item.agentThreadId !== 'string' || !['started', 'completed'].includes(String(item.kind))) throw protocolFailure();
    const callId = item.agentThreadId;
    if (item.kind === 'started') {
      if (this.agents.has(callId) && this.calls.has(callId)) return;
      this.closed.delete(callId);
      this.agents.set(callId, { active: true, ...(typeof item.agentPath === 'string' ? { path: item.agentPath } : {}) });
      this.calls.set(callId, { name: 'spawn_agent', type: 'subAgentActivity', output: '', outputCut: false });
      this.outputProduced = true;
      this.emit('tool_started', { callId, name: 'spawn_agent', input: { ...(typeof item.agentPath === 'string' ? { path: item.agentPath } : {}) } });
    } else if (this.calls.has(callId)) {
      this.calls.delete(callId); this.closed.add(callId);
      const agent = this.agents.get(callId);
      if (agent && !agent.mapper) agent.active = false;
      this.emit('tool_finished', { callId, ok: true, result: { ...(agent?.path === undefined ? {} : { path: agent.path }) } });
    }
  }
  private finishCall(item: Record<string, unknown>): void {
    const callId = item.id as string;
    if (this.closed.has(callId)) return;
    const call = this.calls.get(callId);
    if (!call || call.type !== item.type) throw protocolFailure();
    let ok: boolean, result: unknown, error: string | undefined, outputCut = false;
    if (call.type === 'commandExecution') {
      if (!['completed', 'failed', 'declined'].includes(String(item.status))) throw protocolFailure();
      if (item.aggregatedOutput !== undefined && item.aggregatedOutput !== null && typeof item.aggregatedOutput !== 'string') throw protocolFailure();
      if (item.exitCode !== undefined && item.exitCode !== null && (typeof item.exitCode !== 'number' || !Number.isInteger(item.exitCode))) throw protocolFailure();
      ok = item.status === 'completed' && item.exitCode === 0;
      result = { output: typeof item.aggregatedOutput === 'string' ? item.aggregatedOutput : call.output,
        ...(typeof item.exitCode === 'number' ? { exitCode: item.exitCode } : {}) };
      outputCut = typeof item.aggregatedOutput !== 'string' && call.outputCut;
      if (!ok) error = item.status === 'declined' ? 'declined' : item.status === 'failed' ? 'failed' : `Command exited with ${item.exitCode ?? 'an unknown exit code'}.`;
    } else {
      ok = item.status === undefined || item.status === 'completed';
      if (item.success === false || item.error || item.failure) ok = false;
      result = item.result ?? item;
      if (!ok) error = isObject(item.error) && typeof item.error.message === 'string' ? item.error.message : String(item.status ?? 'failed');
    }
    const bounded = truncateResult(result);
    this.calls.delete(callId); this.closed.add(callId);
    this.emit('tool_finished', { callId, ok, ...bounded, ...(outputCut ? { truncated: true } : {}), ...(error ? { error } : {}) });
  }
}
