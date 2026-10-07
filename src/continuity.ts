import { createHash } from 'node:crypto';
import { readdir, rm } from 'node:fs/promises';
import { isAbsolute, join } from 'node:path';
import { errno, Failure } from './errors.js';
import type { HistoryItem, RunRequest } from './run-request.js';
import { isObject } from './settings.js';
import { ownerAlive, parseOwner, readJson, writeJson } from './state.js';
import type { State } from './state.js';

export const digest = (text: string | Buffer): string => createHash('sha256').update(text).digest('hex');
export const chatKey = (chatSessionId: string): string => digest(chatSessionId);
export interface Fingerprint { messages: number; digest: string }

/** Hash the contract's JSON tuples without retaining the reply text. */
export class MessageDigest {
  private hash = createHash('sha256').update('[');
  private assistant = false;
  // Two adjacent reply blocks may split a UTF-16 surrogate pair. JSON.stringify
  // must see the pair together, as it would after joining the complete reply.
  private trailingSurrogate = '';
  messages = 0;

  add(item: HistoryItem): void {
    if (item.type !== 'message') return;
    if (item.role === 'assistant') {
      if (!this.assistant) {
        this.separator(); this.hash.update('["assistant","');
        this.assistant = true; this.messages++;
      }
      let text = this.trailingSurrogate + item.text;
      this.trailingSurrogate = '';
      const last = text.charCodeAt(text.length - 1);
      if (last >= 0xd800 && last <= 0xdbff) {
        this.trailingSurrogate = text.slice(-1); text = text.slice(0, -1);
      }
      this.hash.update(JSON.stringify(text).slice(1, -1));
    } else {
      this.separator();
      this.hash.update(JSON.stringify(['user', item.text, (item.images ?? []).map(image =>
        [image.mediaType, digest(Buffer.from(image.data, 'base64'))])]));
      this.messages++;
    }
  }

  private separator(): void {
    if (this.assistant) {
      this.hash.update(JSON.stringify(this.trailingSurrogate).slice(1, -1)).update('"]');
      this.trailingSurrogate = ''; this.assistant = false;
    }
    if (this.messages) this.hash.update(',');
  }

  snapshot(): Fingerprint {
    const hash = this.hash.copy();
    if (this.assistant) hash.update(JSON.stringify(this.trailingSurrogate).slice(1, -1)).update('"]');
    return { messages: this.messages, digest: hash.update(']').digest('hex') };
  }
}

export function messageDigest(items: readonly HistoryItem[]): Fingerprint {
  const fingerprint = new MessageDigest();
  for (const item of items) fingerprint.add(item);
  return fingerprint.snapshot();
}

export type RebuildReason = 'no_chat_session' | 'first_run' | 'history_differs' | 'working_folder_changed'
  | 'system_prompt_changed' | 'conversation_gone' | 'in_use' | 'resume_refused';
export interface ContinuityPlan {
  continuity: 'fresh' | 'resumed' | 'rebuilt';
  rebuildReason?: RebuildReason;
  conversation?: string;
  continuedConversation?: string;
}
export interface ChatEntry {
  chatSessionId: string;
  conversation: string;
  workingDirectory: string;
  messages: number;
  digest: string;
  systemPromptDigest: string;
  writtenAt: string;
}

/** Only inspect vendor filenames; conversation contents remain in the vendor home. */
export async function savedConversation(home: string, conversation: string): Promise<boolean> {
  const suffix = '-' + conversation + '.jsonl';
  const visit = async (directory: string): Promise<boolean> => {
    const entries = await readdir(directory, { withFileTypes: true }).catch(error => {
      if (errno(error, 'ENOENT')) return [];
      throw error;
    });
    for (const entry of entries) {
      if (entry.isFile() && entry.name.startsWith('rollout-') && entry.name.endsWith(suffix)) return true;
      if (entry.isDirectory() && await visit(join(directory, entry.name))) return true;
    }
    return false;
  };
  return await visit(join(home, 'sessions')) || await visit(join(home, 'archived_sessions'));
}

export class Chats {
  constructor(readonly state: State) {}

  path(subscriptionId: string, key: string): string {
    if (!/^[a-f0-9]{64}$/.test(key)) throw new Failure('invalid_input', 'The chat key is not a SHA-256 digest.');
    return join(this.state.subscription(subscriptionId), 'chats', key + '.json');
  }

  async entry(subscriptionId: string, key: string): Promise<ChatEntry | undefined> {
    const value = await readJson(this.path(subscriptionId, key));
    if (value === undefined) return undefined;
    if (!isObject(value) || typeof value.chatSessionId !== 'string' || !value.chatSessionId || chatKey(value.chatSessionId) !== key ||
      typeof value.conversation !== 'string' || !value.conversation || typeof value.workingDirectory !== 'string' || !isAbsolute(value.workingDirectory) ||
      !Number.isSafeInteger(value.messages) || (value.messages as number) < 0 ||
      typeof value.digest !== 'string' || !/^[a-f0-9]{64}$/.test(value.digest) ||
      typeof value.systemPromptDigest !== 'string' || !/^[a-f0-9]{64}$/.test(value.systemPromptDigest) ||
      typeof value.writtenAt !== 'string' || !Number.isFinite(Date.parse(value.writtenAt))) {
      throw new Failure('internal', 'Malformed chat map entry.');
    }
    return { chatSessionId: value.chatSessionId, conversation: value.conversation, workingDirectory: value.workingDirectory,
      messages: value.messages as number, digest: value.digest, systemPromptDigest: value.systemPromptDigest, writtenAt: value.writtenAt };
  }

  // Selection and the publication of its run reservation must happen in the same
  // Subscription lock. Cleanup has already run outside that lock; this read does
  // not call Runs.list(), which may itself acquire a lock to clean dead owners.
  async select(request: RunRequest, home: string): Promise<ContinuityPlan> {
    if (!request.history.length) return { continuity: 'fresh' };
    const rebuilt = (rebuildReason: RebuildReason): ContinuityPlan => ({ continuity: 'rebuilt', rebuildReason });
    if (request.chatSessionId === undefined || request.workingDirectory === undefined) return rebuilt('no_chat_session');
    const entry = await this.entry(request.subscriptionId, chatKey(request.chatSessionId));
    if (!entry) return rebuilt('first_run');
    const fingerprint = messageDigest(request.history);
    if (entry.messages !== fingerprint.messages || entry.digest !== fingerprint.digest) return rebuilt('history_differs');
    if (entry.workingDirectory !== request.workingDirectory) return rebuilt('working_folder_changed');
    if (entry.systemPromptDigest !== digest(request.systemPrompt ?? '')) return rebuilt('system_prompt_changed');
    if (!await savedConversation(home, entry.conversation)) return rebuilt('conversation_gone');
    if (await this.inUse(request.subscriptionId, entry.conversation)) return rebuilt('in_use');
    return { continuity: 'resumed', conversation: entry.conversation, continuedConversation: entry.conversation };
  }

  private async inUse(subscriptionId: string, conversation: string): Promise<boolean> {
    const directory = join(this.state.directory, 'runs');
    const files = await readdir(directory).catch(error => { if (errno(error, 'ENOENT')) return []; throw error; });
    for (const file of files) {
      if (!file.endsWith('.json') || file.startsWith('.')) continue;
      const record = await readJson(join(directory, file));
      if (record === undefined) continue;
      if (!isObject(record) || typeof record.runId !== 'string' || file !== record.runId + '.json' || typeof record.subscriptionId !== 'string') {
        throw new Failure('internal', 'Malformed run record.');
      }
      if (record.subscriptionId === subscriptionId && record.conversation === conversation && await ownerAlive(parseOwner(record.owner))) return true;
    }
    return false;
  }

  async settle(request: RunRequest, plan: ContinuityPlan, conversation: string | undefined,
    fingerprint: Fingerprint, completed: boolean): Promise<void> {
    if (request.chatSessionId === undefined || request.workingDirectory === undefined) return;
    const key = chatKey(request.chatSessionId);
    await this.state.withSubscriptionLock(request.subscriptionId, async () => {
      if (completed) {
        if (!conversation) throw new Failure('internal', 'A completed saved run has no conversation.');
        const entry: ChatEntry = { chatSessionId: request.chatSessionId!, conversation,
          workingDirectory: request.workingDirectory!, messages: fingerprint.messages, digest: fingerprint.digest,
          systemPromptDigest: digest(request.systemPrompt ?? ''), writtenAt: new Date().toISOString() };
        await writeJson(this.path(request.subscriptionId, key), entry);
      } else if (plan.continuedConversation !== undefined &&
        (await this.entry(request.subscriptionId, key))?.conversation === plan.continuedConversation) {
        await rm(this.path(request.subscriptionId, key), { force: true });
      }
    });
  }
}
