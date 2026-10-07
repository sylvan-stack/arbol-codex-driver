import { test } from 'node:test';
import assert from 'node:assert/strict';
import { Failure } from '../src/errors.js';
import { RunEvents, plainCommand, truncateResult } from '../src/run-events.js';

function fixture() {
  const events: Array<{ type: string; [key: string]: unknown }> = [];
  const mapper = new RunEvents('thread', 'turn', 'requested-model', (type, data) => events.push({ type, ...data }));
  const notification = (method: string, data: Record<string, unknown>) => mapper.consume(method, { threadId: 'thread', turnId: 'turn', ...data });
  const item = (method: 'item/started' | 'item/completed', item: Record<string, unknown>) => notification(method, { item });
  const completed = (status = 'completed', error: unknown = null) => mapper.consume('turn/completed', {
    threadId: 'thread', turn: { id: 'turn', status, error, items: [], itemsView: 'summary' },
  });
  return { events, mapper, notification, item, completed };
}

test('run.protocol streams text and reasoning and preserves authoritative complete blocks', () => {
  const { events, mapper, notification, item } = fixture();
  item('item/started', { type: 'userMessage', id: 'user', content: [] });
  item('item/completed', { type: 'userMessage', id: 'user', content: [] });
  item('item/started', { type: 'agentMessage', id: 'text', text: '' });
  notification('item/agentMessage/delta', { itemId: 'text', delta: 'partial' });
  item('item/completed', { type: 'agentMessage', id: 'text', text: 'authoritative text', phase: 'commentary' });
  item('item/started', { type: 'reasoning', id: 'thinking', summary: [] });
  notification('item/reasoning/summaryTextDelta', { itemId: 'thinking', summaryIndex: 0, delta: 'reason' });
  item('item/completed', { type: 'reasoning', id: 'thinking', summary: ['First part', 'Second part'], content: ['unreleased reasoning'] });
  item('item/completed', { type: 'reasoning', id: 'empty', summary: [] });
  item('item/completed', { type: 'agentMessage', id: 'unstreamed', text: 'No deltas needed.' });
  assert.deepEqual(events, [
    { type: 'text_delta', text: 'partial' }, { type: 'text', text: 'authoritative text' },
    { type: 'thinking_delta', text: 'reason' }, { type: 'thinking', text: 'First part\n\nSecond part' },
    { type: 'text', text: 'No deltas needed.' },
  ]);
  assert.equal(mapper.outputProduced, true);
});

test('run.usage sums per-request counts rather than historical thread totals, retaining all reported fields', () => {
  const { mapper, notification, events } = fixture();
  notification('thread/tokenUsage/updated', { tokenUsage: {
    total: { inputTokens: 1000, cachedInputTokens: 800, outputTokens: 300, reasoningOutputTokens: 200 },
    last: { inputTokens: 10, cachedInputTokens: 8, outputTokens: 5, reasoningOutputTokens: 3, cacheWriteInputTokens: 11 },
  } });
  notification('thread/tokenUsage/updated', { tokenUsage: {
    total: { inputTokens: 1020, cachedInputTokens: 816, outputTokens: 307, reasoningOutputTokens: 204 },
    last: { inputTokens: 20, cachedInputTokens: 16, outputTokens: 7, reasoningOutputTokens: 4 },
  } });
  assert.deepEqual(mapper.usage, { model: 'requested-model', inputTokens: 30, cachedInputTokens: 24, outputTokens: 12, reasoningTokens: 7 });
  assert.deepEqual(events.at(-1), { type: 'usage', usage: mapper.usage });
  assert.equal('costUsd' in mapper.usage, false);
  assert.equal('cacheWriteInputTokens' in mapper.usage, false);
  assert.deepEqual(events[0]!.usage, { model: 'requested-model', inputTokens: 10, cachedInputTokens: 8, outputTokens: 5, reasoningTokens: 3 });
  const snapshot = mapper.usage; snapshot.inputTokens = 500;
  assert.equal(mapper.usage.inputTokens, 30);
});

test('run.usage does not double count replayed reports or invent unreported fields', () => {
  const { mapper, notification, events } = fixture();
  const usage = (input: number, output: number, lastInput: number, lastOutput: number) => notification('thread/tokenUsage/updated', {
    tokenUsage: { total: { inputTokens: input, outputTokens: output }, last: { inputTokens: lastInput, outputTokens: lastOutput } },
  });
  usage(3, 2, 3, 2); usage(7, 5, 4, 3); usage(7, 5, 4, 3);
  assert.deepEqual(events.map(event => event.usage), [
    { model: 'requested-model', inputTokens: 3, outputTokens: 2 },
    { model: 'requested-model', inputTokens: 7, outputTokens: 5 },
    { model: 'requested-model', inputTokens: 7, outputTokens: 5 },
  ]);
  assert.deepEqual(mapper.usage, { model: 'requested-model', inputTokens: 7, outputTokens: 5 });
});

test('run.notices preserve retry messages and rerouting changes the reported model', () => {
  const { mapper, notification, events, completed } = fixture();
  notification('error', { error: { message: 'Reconnecting... 2/5', codexErrorInfo: 'other' }, willRetry: true });
  mapper.consume('warning', { threadId: 'thread', message: 'Transport changed.' });
  mapper.consume('deprecationNotice', { summary: 'Deprecated.', details: 'Use the replacement.' });
  notification('model/rerouted', { fromModel: 'requested-model', toModel: 'actual-model', reason: 'rateLimit' });
  assert.deepEqual(events.slice(0, 3), [
    { type: 'notice', code: 'retrying', message: 'Reconnecting... 2/5' },
    { type: 'notice', code: 'warning', message: 'Transport changed.' },
    { type: 'notice', code: 'deprecation', message: 'Deprecated.\nUse the replacement.' },
  ]);
  assert.equal(mapper.usage.model, 'actual-model');
  assert.deepEqual(events.at(-1), { type: 'usage', usage: { model: 'actual-model' } });
  completed();
  assert.equal(mapper.outcome, 'completed'); assert.equal(mapper.error, undefined);
});

test('run.protocol passes over foreign threads once and rejects another turn of its own thread', () => {
  const { mapper, events } = fixture();
  for (const threadId of ['foreign', 'another-foreign']) mapper.consume('item/agentMessage/delta', { threadId, turnId: 'foreign-turn', delta: 'private foreign text' });
  assert.deepEqual(events, [{ type: 'notice', code: 'foreign_thread', message: 'A notification for another codex thread was ignored.' }]);
  assert.equal(mapper.outputProduced, false);
  assert.throws(() => mapper.consume('thread/status/changed', { threadId: 'thread', turnId: 'other-turn' }),
    (error: unknown) => error instanceof Failure && error.result.code === 'tool_failed');
  assert.throws(() => mapper.consume('turn/completed', { threadId: 'thread', turn: { id: 'other-turn', status: 'completed' } }), Failure);
});

test('stop.collaboration-spawn buffers concurrent receivers and ignores unrelated threads after discovery', () => {
  const { mapper, events, item } = fixture();
  const spawn = (id: string) => ({ type: 'collabAgentToolCall', id, tool: 'spawnAgent', status: 'inProgress', receiverThreadIds: [] });
  item('item/started', spawn('spawn-a')); item('item/started', spawn('spawn-b'));
  for (const threadId of ['child-a', 'unrelated', 'child-b']) mapper.consume('item/agentMessage/delta', { threadId, turnId: threadId + '-turn', delta: threadId });
  item('item/completed', { ...spawn('spawn-a'), status: 'completed', receiverThreadIds: ['child-a'] });
  assert.ok(events.some(event => event.type === 'text_delta' && event.text === 'child-a' && event.parentCallId === 'spawn-a'));
  assert.equal(events.some(event => event.code === 'foreign_thread'), false);
  item('item/completed', { ...spawn('spawn-b'), status: 'completed', receiverThreadIds: ['child-b'] });
  assert.ok(events.some(event => event.type === 'text_delta' && event.text === 'child-b' && event.parentCallId === 'spawn-b'));
  assert.equal(events.filter(event => event.code === 'foreign_thread').length, 1);
  assert.equal(events.some(event => event.text === 'unrelated'), false);
  assert.deepEqual(mapper.activeTurns, [{ threadId: 'thread', turnId: 'turn' },
    { threadId: 'child-a', turnId: 'child-a-turn' }, { threadId: 'child-b', turnId: 'child-b-turn' }]);
});

test('stop.collaboration-spawn discovers a grandchild announced by an active child spawn', () => {
  const { mapper, events, item } = fixture();
  item('item/started', { type: 'subAgentActivity', id: 'activity', kind: 'started', agentThreadId: 'child' });
  mapper.consume('turn/started', { threadId: 'child', turn: { id: 'child-turn' } });
  const spawn = { type: 'collabAgentToolCall', id: 'nested-spawn', tool: 'spawnAgent', status: 'inProgress', receiverThreadIds: [] };
  mapper.consume('item/started', { threadId: 'child', turnId: 'child-turn', item: spawn });
  mapper.consume('turn/started', { threadId: 'grandchild', turn: { id: 'grandchild-turn' } });
  mapper.consume('item/completed', { threadId: 'child', turnId: 'child-turn', item: { ...spawn, status: 'completed', receiverThreadIds: ['grandchild'] } });
  mapper.consume('item/agentMessage/delta', { threadId: 'grandchild', turnId: 'grandchild-turn', delta: 'nested output' });
  assert.ok(events.some(event => event.type === 'text_delta' && event.text === 'nested output' && event.parentCallId === 'nested-spawn'));
  assert.ok(mapper.activeTurns.some(turn => turn.threadId === 'grandchild' && turn.turnId === 'grandchild-turn'));
  assert.equal(events.some(event => event.code === 'foreign_thread'), false);
});

test('run.outcomes never emit a final event before cleanup', () => {
  for (const status of ['completed', 'failed', 'interrupted'] as const) {
    const { mapper, events, completed } = fixture();
    completed(status, status === 'failed' ? { message: 'Vendor refused.', codexErrorInfo: 'other' } : null);
    assert.equal(mapper.outcome, status);
    assert.equal(mapper.error?.message, status === 'failed' ? 'Vendor refused.' : undefined);
    assert.equal(events.some(event => event.type === 'finished'), false);
  }
  const { mapper, notification, completed } = fixture();
  notification('error', { error: { message: 'Vendor refused.', codexErrorInfo: 'other' }, willRetry: false });
  assert.equal(mapper.outcome, undefined);
  completed('completed');
  assert.equal(mapper.outcome, 'failed');
  assert.deepEqual(mapper.error, { code: 'vendor_error', message: 'Vendor refused.', retryable: false });
});

test('run.tools report shell calls in the common form with text before the tool start', () => {
  const { mapper, events, item, notification } = fixture();
  item('item/completed', { type: 'agentMessage', id: 'preface', text: 'I will run the command.' });
  item('item/started', { type: 'commandExecution', id: 'command', command: "/bin/zsh -lc 'printf fixture-output'", cwd: '/work', status: 'inProgress' });
  notification('item/commandExecution/outputDelta', { itemId: 'command', delta: 'fixture-' });
  notification('item/commandExecution/outputDelta', { itemId: 'command', delta: 'output' });
  item('item/completed', { type: 'commandExecution', id: 'command', command: "/bin/zsh -lc 'printf fixture-output'", cwd: '/work', status: 'completed', exitCode: 0, aggregatedOutput: 'fixture-output' });
  assert.deepEqual(events, [
    { type: 'text', text: 'I will run the command.' },
    { type: 'tool_started', callId: 'command', name: 'shell', input: { command: 'printf fixture-output', cwd: '/work' } },
    { type: 'tool_output_delta', callId: 'command', text: 'fixture-' },
    { type: 'tool_output_delta', callId: 'command', text: 'output' },
    { type: 'tool_finished', callId: 'command', ok: true, result: { output: 'fixture-output', exitCode: 0 } },
  ]);
  assert.equal(mapper.openCalls.size, 0); assert.deepEqual(mapper.unfinishedCalls, []);
});

test('run.tools keep a background shell call open after the turn has completed', () => {
  const { mapper, events, item, notification, completed } = fixture();
  item('item/started', { type: 'commandExecution', id: 'background', command: 'slow-command', status: 'inProgress' });
  completed();
  assert.equal(mapper.openCalls.get('background')!.type, 'commandExecution');
  notification('item/commandExecution/outputDelta', { itemId: 'background', delta: 'late output' });
  item('item/completed', { type: 'commandExecution', id: 'background', status: 'completed', exitCode: 0, aggregatedOutput: null });
  assert.deepEqual(events.at(-1), { type: 'tool_finished', callId: 'background', ok: true, result: { output: 'late output', exitCode: 0 } });
  assert.equal(mapper.outcome, 'completed');
  assert.equal(mapper.openCalls.size, 0);
});

test('run.tools map declined, failed and nonzero shell exits as tool failures without failing the turn', () => {
  for (const [status, exitCode, error] of [['declined', null, 'declined'], ['failed', null, 'failed'], ['completed', 2, 'Command exited with 2.']] as const) {
    const { mapper, events, item, completed } = fixture();
    item('item/started', { type: 'commandExecution', id: 'command', command: 'false', status: 'inProgress' });
    item('item/completed', { type: 'commandExecution', id: 'command', status, exitCode, aggregatedOutput: '' });
    assert.equal(events.at(-1)!.ok, false); assert.equal(events.at(-1)!.error, error);
    completed(); assert.equal(mapper.outcome, 'completed');
  }
});

test('run.tools map patch changes and opaque tools and close each call exactly once', () => {
  const { mapper, events, item } = fixture();
  const patch = { type: 'fileChange', id: 'patch', status: 'inProgress', changes: [{ path: '/work/a', kind: { type: 'update', move_path: '/work/b' }, diff: '+new' }] };
  item('item/started', patch);
  item('item/completed', { ...patch, status: 'declined' });
  assert.deepEqual(events[0], { type: 'tool_started', callId: 'patch', name: 'apply_patch', input: [{ path: '/work/a', kind: { type: 'update', move_path: '/work/b' }, content: '+new' }] });
  assert.equal(events[1]!.ok, false); assert.equal(events[1]!.error, 'declined');
  const web = { type: 'webSearch', id: 'web', query: 'query' };
  item('item/started', web); item('item/completed', web); item('item/completed', web);
  assert.equal(events.filter(event => event.callId === 'web' && event.type === 'tool_started').length, 1);
  assert.equal(events.filter(event => event.callId === 'web' && event.type === 'tool_finished').length, 1);
  assert.equal(mapper.openCalls.size, 0);
});

test('run.outcomes report calls left unfinished by the tool even after closing the events', () => {
  const { mapper, events, item } = fixture();
  item('item/started', { type: 'commandExecution', id: 'unfinished', command: 'sleep 99', status: 'inProgress' });
  assert.equal(mapper.outputProduced, true);
  mapper.closeOpenCalls(); mapper.closeOpenCalls();
  assert.deepEqual(mapper.unfinishedCalls, ['unfinished']); assert.equal(mapper.openCalls.size, 0);
  assert.deepEqual(events.at(-1), { type: 'tool_finished', callId: 'unfinished', ok: false, error: 'The run ended before the tool call finished.', interrupted: true });
  item('item/completed', { type: 'commandExecution', id: 'unfinished', status: 'completed', exitCode: 0 });
  assert.equal(events.filter(event => event.type === 'tool_finished').length, 1);
});

test('run.truncation bounds string, object and streamed results to 200 KiB without breaking UTF-8', () => {
  const limit = 200 * 1024, large = '🦊'.repeat(limit);
  for (const result of [large, { content: large }]) {
    const bounded = truncateResult(result);
    assert.equal(bounded.truncated, true);
    assert.equal(typeof bounded.result, 'string');
    assert.ok(Buffer.byteLength(bounded.result as string) <= limit);
    assert.equal((bounded.result as string).includes('�'), false);
  }
  assert.deepEqual(truncateResult({ output: 'small', exitCode: 0 }), { result: { output: 'small', exitCode: 0 } });
  const { mapper, events, item, notification } = fixture();
  item('item/started', { type: 'commandExecution', id: 'big', command: 'big-output', status: 'inProgress' });
  notification('item/commandExecution/outputDelta', { itemId: 'big', delta: large });
  notification('item/commandExecution/outputDelta', { itemId: 'big', delta: 'tail' });
  item('item/completed', { type: 'commandExecution', id: 'big', status: 'completed', exitCode: 0, aggregatedOutput: null });
  assert.equal(events.at(-1)!.truncated, true);
  assert.ok(Buffer.byteLength(String(events.at(-1)!.result)) <= limit);
  assert.equal(mapper.openCalls.size, 0);
});

test('run.shell unwraps one launcher while preserving quoting inside the command', () => {
  assert.equal(plainCommand("/bin/zsh -lc 'echo hi'"), 'echo hi');
  assert.equal(plainCommand("/bin/bash -c 'printf '\\''single'\\'''"), "printf 'single'");
  assert.equal(plainCommand('/bin/sh -c "echo \\$HOME"'), 'echo $HOME');
  for (const command of ['echo "$HOME"', 'bash -lc "echo hi" extra', 'zsh -c "unterminated', 'echo a && echo b']) assert.equal(plainCommand(command), command);
});

test('run.protocol rejects malformed notifications without hiding earlier output', () => {
  const { mapper, events, notification, item } = fixture();
  notification('item/agentMessage/delta', { delta: 'kept' });
  assert.throws(() => notification('item/agentMessage/delta', { delta: 4 }), Failure);
  assert.throws(() => item('item/completed', { type: 'reasoning', id: 'bad-summary', summary: [null] }), Failure);
  assert.throws(() => notification('thread/tokenUsage/updated', { tokenUsage: {} }), Failure);
  assert.throws(() => item('item/completed', { type: 'commandExecution', id: 'unknown-call', status: 'completed', exitCode: 0 }), Failure);
  assert.throws(() => mapper.consume('turn/completed', null), Failure);
  assert.deepEqual(events, [{ type: 'text_delta', text: 'kept' }]);
});
