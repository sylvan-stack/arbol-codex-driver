import { test } from 'node:test';
import type { TestContext } from 'node:test';
import assert from 'node:assert/strict';
import { createHash, randomUUID } from 'node:crypto';
import { mkdir, readFile, realpath, rm, stat, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { Chats, MessageDigest, chatKey, digest, messageDigest, savedConversation } from '../src/continuity.js';
import type { ChatEntry } from '../src/continuity.js';
import { Failure } from '../src/errors.js';
import { readRunRequest } from '../src/run-request.js';
import type { HistoryItem } from '../src/run-request.js';
import { Runs } from '../src/runs.js';
import { State, privateDirectory, processOwner, writeJson } from '../src/state.js';
import { fixture } from './helpers.js';

const image = { mediaType: 'image/png' as const, data: 'aQ==' };
const user: HistoryItem = { type: 'message', role: 'user', text: 'private-history-user', images: [image] };
const call: HistoryItem = { type: 'tool_call', name: 'shell', input: { command: 'private-shell-command' },
  ok: false, result: { output: 'private-output', exitCode: 3 }, error: 'private-error' };
const history: HistoryItem[] = [user, { type: 'message', role: 'assistant', text: 'a"\n\\😀' }, call,
  { type: 'message', role: 'assistant', text: 'b' }];
const sha256 = (text: string | Buffer): string => createHash('sha256').update(text).digest('hex');

test('continuity.digest hashes exact message tuples, decoded pictures and joined assistant replies', () => {
  const canonical = [['user', user.text, [['image/png', sha256(Buffer.from('i'))]]], ['assistant', 'a"\n\\😀b']];
  assert.deepEqual(messageDigest(history), { messages: 2, digest: sha256(JSON.stringify(canonical)) });
  assert.deepEqual(messageDigest([]), { messages: 0, digest: sha256('[]') });
  assert.equal(digest(''), 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855');
  assert.deepEqual(messageDigest([{ ...user, images: [{ ...image, data: 'aR==' }] }, ...history.slice(1)]), messageDigest(history));
  assert.notEqual(messageDigest([{ ...user, text: 'edited' }, ...history.slice(1)]).digest, messageDigest(history).digest);
  assert.notEqual(messageDigest([user, { type: 'message', role: 'assistant', text: 'replaced' }]).digest, messageDigest(history).digest);
  assert.notEqual(messageDigest([{ ...user, images: [{ ...image, mediaType: 'image/jpeg' }] }, ...history.slice(1)]).digest, messageDigest(history).digest);
  assert.deepEqual(messageDigest([{ type: 'message', role: 'user', text: '' }]),
    { messages: 1, digest: sha256('[["user","",[]]]') });
  assert.deepEqual(messageDigest([call]), { messages: 0, digest: sha256('[]') });
});

test('continuity.digest streaming snapshots preserve assistant blocks and split UTF-16 pairs', () => {
  const stream = new MessageDigest();
  const first: HistoryItem = { type: 'message', role: 'assistant', text: 'start\ud83d' };
  stream.add(first);
  const before = { messages: 1, digest: sha256(JSON.stringify([['assistant', first.text]])) };
  assert.deepEqual(stream.snapshot(), before); assert.deepEqual(stream.snapshot(), before);
  stream.add(call); stream.add({ type: 'message', role: 'assistant', text: '' });
  stream.add({ type: 'message', role: 'assistant', text: '\ude00"\nend\ud800' });
  assert.deepEqual(stream.snapshot(), { messages: 1, digest: sha256(JSON.stringify([['assistant', 'start😀"\nend\ud800']])) });
  stream.add({ type: 'message', role: 'user', text: 'next' });
  stream.add({ type: 'message', role: 'assistant', text: '' });
  assert.deepEqual(stream.snapshot(), { messages: 3, digest: sha256(JSON.stringify([
    ['assistant', 'start😀"\nend\ud800'], ['user', 'next', []], ['assistant', ''],
  ])) });
});

async function setup(t: TestContext) {
  const f = await fixture(t);
  const state = new State(f.state); await state.initialize();
  const work = join(f.home, 'work'); await mkdir(work);
  const cwd = await realpath(work);
  const request = { ...await readRunRequest({ tools: 'none', cwd, 'chat-session': 'opaque/../chat', 'run-id': 'selected' },
    { message: 'private-new-input' }), history, systemPrompt: 'private-system-prompt' };
  const chats = new Chats(state), runs = new Runs(state), conversation = randomUUID();
  const home = join(state.subscription(request.subscriptionId), 'home');
  const rollout = join(home, 'sessions', '2026', '10', '07', `rollout-2026-10-07T00-00-00-${conversation}.jsonl`);
  await privateDirectory(join(home, 'sessions', '2026', '10', '07')); await writeFile(rollout, 'not read by continuity', { mode: 0o600 });
  const entry: ChatEntry = { chatSessionId: request.chatSessionId!, conversation, workingDirectory: cwd,
    ...messageDigest(history), systemPromptDigest: digest(request.systemPrompt), writtenAt: '2026-10-07T00:00:00.000Z' };
  const path = chats.path(request.subscriptionId, chatKey(request.chatSessionId!));
  await writeJson(path, entry);
  const select = () => state.withSubscriptionLock(request.subscriptionId, () => chats.select(request, home));
  return { f, state, cwd, request, chats, runs, home, entry, path, rollout, select };
}

test('continuity.map uses opaque hashed chat names, Subscription isolation and owner-only files without messages', async t => {
  const { state, request, chats, entry, path } = await setup(t);
  assert.equal(path, join(state.subscription(request.subscriptionId), 'chats', sha256(request.chatSessionId!) + '.json'));
  assert.equal(await chats.entry('another-subscription', chatKey(request.chatSessionId!)), undefined);
  assert.equal(await chats.entry(request.subscriptionId, chatKey('another-chat')), undefined);
  const transcript = messageDigest([...history, { type: 'message', ...request.input },
    { type: 'message', role: 'assistant', text: 'private-new-reply' }]);
  await chats.settle(request, { continuity: 'fresh' }, entry.conversation, transcript, true);
  const saved = await readFile(path, 'utf8');
  for (const privateText of [user.text, 'private-shell-command', 'private-output', 'private-error',
    request.systemPrompt, request.input.text, 'private-new-reply', image.data]) assert.equal(saved.includes(privateText), false);
  const parsed = JSON.parse(saved);
  assert.deepEqual(Object.keys(parsed).sort(), ['chatSessionId', 'conversation', 'digest', 'messages', 'systemPromptDigest', 'workingDirectory', 'writtenAt']);
  assert.equal(parsed.messages, 4); assert.equal(parsed.digest, transcript.digest);
  assert.equal(parsed.systemPromptDigest, sha256(request.systemPrompt));
  assert.equal((await stat(path)).mode & 0o777, 0o600);
  assert.equal((await stat(join(state.subscription(request.subscriptionId), 'chats'))).mode & 0o777, 0o700);
  assert.equal(await stat(join(state.subscription(request.subscriptionId), 'lock')).then(() => true).catch(() => false), false);
});

test('continuity.selection reports the first failed check and checks the Codex system prompt', async t => {
  const { request, chats, home, entry, path, rollout, select } = await setup(t);
  assert.deepEqual(await select(), { continuity: 'resumed', conversation: entry.conversation, continuedConversation: entry.conversation });
  assert.deepEqual(await chats.select({ ...request, history: [] }, home), { continuity: 'fresh' });
  assert.equal((await chats.select({ ...request, chatSessionId: undefined, workingDirectory: undefined }, home)).rebuildReason, 'no_chat_session');
  assert.equal((await chats.select({ ...request, chatSessionId: 'missing', workingDirectory: '/changed', systemPrompt: 'changed' }, home)).rebuildReason, 'first_run');
  await writeJson(path, { ...entry, messages: entry.messages + 1, workingDirectory: '/changed', systemPromptDigest: sha256('changed') });
  assert.equal((await select()).rebuildReason, 'history_differs');
  await writeJson(path, { ...entry, digest: sha256('different') });
  assert.equal((await select()).rebuildReason, 'history_differs');
  await writeJson(path, { ...entry, workingDirectory: '/changed', systemPromptDigest: sha256('changed') });
  assert.equal((await select()).rebuildReason, 'working_folder_changed');
  await writeJson(path, { ...entry, systemPromptDigest: sha256('changed') }); await rm(rollout);
  assert.equal((await select()).rebuildReason, 'system_prompt_changed');
  await writeJson(path, entry);
  assert.equal((await select()).rebuildReason, 'conversation_gone');
});

test('continuity.selection finds archived saved threads by filename without reading their content', async t => {
  const { home, entry, rollout, select } = await setup(t);
  await rm(rollout);
  await privateDirectory(join(home, 'archived_sessions', 'nested'));
  await writeFile(join(home, 'archived_sessions', 'nested', `rollout-date-${entry.conversation}.jsonl`), 'malformed vendor content');
  assert.equal(await savedConversation(home, entry.conversation), true);
  assert.equal((await select()).continuity, 'resumed');
  assert.equal(await savedConversation(home, 'absent'), false);
  assert.equal(await savedConversation(join(home, 'missing'), entry.conversation), false);
});

test('continuity.concurrent selection and published run reservations let only one run resume', async t => {
  const { state, request, chats, runs, home, entry } = await setup(t);
  const choices = await Promise.all(['one', 'two'].map(runId => state.withSubscriptionLock(request.subscriptionId, async () => {
    const record = await runs.reserve({ runId, subscriptionId: request.subscriptionId, chatSessionId: request.chatSessionId! });
    const plan = await chats.select({ ...request, runId }, home);
    if (plan.conversation !== undefined) { record.conversation = plan.conversation; await runs.save(record); }
    return plan;
  })));
  assert.deepEqual(choices.map(plan => plan.continuity).sort(), ['rebuilt', 'resumed']);
  assert.equal(choices.find(plan => plan.continuity === 'rebuilt')?.rebuildReason, 'in_use');
  assert.equal(choices.find(plan => plan.continuity === 'resumed')?.conversation, entry.conversation);
  assert.equal((await runs.list()).length, 2);
});

test('continuity.selection checks gone before in-use and ignores dead or reused owners and other Subscriptions', async t => {
  const { state, request, chats, home, entry, rollout, select } = await setup(t);
  const owner = await processOwner(process.pid); assert.ok(owner);
  const record = { runId: 'occupied', subscriptionId: request.subscriptionId, owner, startedAt: new Date().toISOString(), conversation: entry.conversation };
  const path = join(state.directory, 'runs', 'occupied.json');
  await writeJson(path, record); assert.equal((await select()).rebuildReason, 'in_use');
  await rm(rollout); assert.equal((await select()).rebuildReason, 'conversation_gone');
  await writeFile(rollout, 'present');
  await writeJson(path, { ...record, owner: { ...owner, startedAt: '1970-01-01T00:00:00.000Z' } });
  assert.equal((await select()).continuity, 'resumed');
  await writeJson(path, { ...record, subscriptionId: 'another-subscription' });
  assert.equal((await chats.select(request, home)).continuity, 'resumed');
});

test('continuity.map removes only a failed run’s continued conversation and preserves a newer completion', async t => {
  const { request, chats, entry, path, select } = await setup(t);
  const plan = await select(), replacement = randomUUID(), fingerprint = messageDigest(history);
  await chats.settle(request, { ...plan, continuity: 'rebuilt', rebuildReason: 'resume_refused' }, undefined, fingerprint, false);
  assert.equal(await chats.entry(request.subscriptionId, chatKey(request.chatSessionId!)), undefined);
  await writeJson(path, entry);
  await chats.settle(request, { continuity: 'rebuilt', rebuildReason: 'in_use' }, undefined, fingerprint, false);
  assert.equal((await chats.entry(request.subscriptionId, chatKey(request.chatSessionId!)))?.conversation, entry.conversation);
  await chats.settle(request, { continuity: 'rebuilt', rebuildReason: 'in_use' }, replacement, fingerprint, true);
  await chats.settle(request, plan, undefined, fingerprint, false);
  assert.equal((await chats.entry(request.subscriptionId, chatKey(request.chatSessionId!)))?.conversation, replacement);
  await chats.settle(request, plan, entry.conversation, fingerprint, true);
  assert.equal((await chats.entry(request.subscriptionId, chatKey(request.chatSessionId!)))?.conversation, entry.conversation);
});

test('continuity.map killed-run cleanup invalidates a continued conversation and preserves a newer map', async t => {
  const { state, request, chats, runs, entry, path } = await setup(t);
  const key = chatKey(request.chatSessionId!);
  const record = { runId: 'killed', subscriptionId: request.subscriptionId,
    owner: { pid: process.pid, startedAt: '1970-01-01T00:00:00.000Z' }, startedAt: '2026-10-07T00:00:00.000Z',
    chatKey: key, conversation: entry.conversation, continuedConversation: entry.conversation };
  const scratch = join(state.directory, 'tmp', record.runId);
  await privateDirectory(scratch); await writeFile(join(scratch, 'leftover'), 'scratch');
  await writeJson(runs.path(record.runId), record);
  assert.deepEqual(await runs.list(), []);
  assert.equal(await chats.entry(request.subscriptionId, key), undefined);
  assert.equal(await stat(scratch).then(() => true).catch(() => false), false);
  assert.equal(await stat(runs.path(record.runId)).then(() => true).catch(() => false), false);
  const newer = randomUUID();
  await writeJson(path, { ...entry, conversation: newer }); await writeJson(runs.path(record.runId), record);
  assert.deepEqual(await runs.list(), []);
  assert.equal((await chats.entry(request.subscriptionId, key))?.conversation, newer);
});

test('continuity.map does not write or resume ephemeral runs or requests without a chat session', async t => {
  const { request, chats, home, entry, path } = await setup(t);
  const previous = await readFile(path, 'utf8');
  const ephemeral = { ...request, workingDirectory: undefined };
  assert.equal((await chats.select(ephemeral, home)).rebuildReason, 'no_chat_session');
  await chats.settle(ephemeral, { continuity: 'rebuilt', rebuildReason: 'no_chat_session' }, randomUUID(), messageDigest(history), true);
  await chats.settle({ ...request, chatSessionId: undefined }, { continuity: 'rebuilt', rebuildReason: 'no_chat_session' },
    randomUUID(), messageDigest(history), true);
  assert.equal(await readFile(path, 'utf8'), previous);
  assert.equal((await chats.entry(request.subscriptionId, chatKey(request.chatSessionId!)))?.conversation, entry.conversation);
});

test('continuity.map refuses malformed entries without exposing their contents', async t => {
  const { request, chats, entry, path } = await setup(t);
  const privateText = 'malformed-private-entry';
  for (const malformed of [{ ...entry, chatSessionId: privateText }, { ...entry, conversation: null },
    { ...entry, workingDirectory: 'relative' }, { ...entry, messages: -1 }, { ...entry, messages: 1.5 },
    { ...entry, digest: privateText }, { ...entry, systemPromptDigest: privateText }, { ...entry, writtenAt: privateText }]) {
    await writeJson(path, malformed);
    await assert.rejects(chats.entry(request.subscriptionId, chatKey(request.chatSessionId!)), (error: unknown) => {
      assert.ok(error instanceof Failure); assert.equal(error.result.code, 'internal');
      assert.equal(JSON.stringify(error.result).includes(privateText), false); return true;
    });
  }
  assert.throws(() => chats.path(request.subscriptionId, '../unsafe'), (error: unknown) =>
    error instanceof Failure && error.result.code === 'invalid_input');
});
