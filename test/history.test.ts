import assert from 'node:assert/strict';
import { test } from 'node:test';
import { mkdtemp, readFile, readdir, rm, stat } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { historyItems, labelledHistoryInput, prepareTurnInput, toolResultText } from '../src/history.js';
import type { HistoryItem, Image } from '../src/run-request.js';

const picture: Image = { mediaType: 'image/png', data: 'aQ==' };
const otherPicture: Image = { mediaType: 'image/jpeg', data: 'ag==' };
type ToolCall = Extract<HistoryItem, { type: 'tool_call' }>;

test('history.native preserves messages, images and cross-Driver tool calls in one ordered item array', () => {
  const history: HistoryItem[] = [
    { type: 'message', role: 'user', text: 'A "quote"\n😀', images: [picture, otherPicture] },
    { type: 'message', role: 'assistant', text: 'Before' },
    { type: 'tool_call', name: 'shell', input: { command: 'pwd', cwd: '/repository', vendorField: 'omit' },
      ok: true, result: { output: '/repository\n', exitCode: 0 } },
    { type: 'message', role: 'assistant', text: 'After', images: [picture] },
    { type: 'tool_call', name: 'Bash', input: { command: 'echo value', description: 'other Driver' }, ok: false,
      result: { output: 'partial', exitCode: 2, truncated: true }, error: 'declined' },
    { type: 'message', role: 'assistant', text: 'Final' },
  ];
  const original = JSON.stringify(history);
  const items = historyItems(history);
  assert.equal(items.length, 8);
  assert.deepEqual(items[0], { type: 'message', role: 'user', content: [
    { type: 'input_text', text: history[0]!.type === 'message' ? history[0]!.text : '' },
    { type: 'input_image', image_url: 'data:image/png;base64,aQ==' },
    { type: 'input_image', image_url: 'data:image/jpeg;base64,ag==' },
  ] });
  assert.deepEqual(items[1], { type: 'message', role: 'assistant', content: [{ type: 'output_text', text: 'Before' }] });
  const shell = items[2]!;
  assert.deepEqual(shell, { type: 'function_call', name: 'shell', arguments: '{"command":"pwd","cwd":"/repository"}', call_id: shell.call_id });
  assert.deepEqual(items[3], { type: 'function_call_output', call_id: shell.call_id, output: '/repository\n' });
  assert.deepEqual(items[4], { type: 'message', role: 'assistant', content: [
    { type: 'output_text', text: 'After' }, { type: 'input_image', image_url: 'data:image/png;base64,aQ==' },
  ] });
  const crossDriver = items[5]!;
  assert.equal(crossDriver.name, 'Bash');
  assert.equal(crossDriver.arguments, '{"command":"echo value","description":"other Driver"}');
  assert.deepEqual(items[6], { type: 'function_call_output', call_id: crossDriver.call_id,
    output: '{"output":"partial","exitCode":2,"truncated":true}\ndeclined' });
  assert.deepEqual(items[7], { type: 'message', role: 'assistant', content: [{ type: 'output_text', text: 'Final' }] });
  assert.equal(JSON.stringify(history), original);
});

test('history.native fabricates a fresh paired call identifier for every call', () => {
  const call: ToolCall = { type: 'tool_call', name: 'shell', input: { command: 'true' }, ok: true };
  const first = historyItems([call, call]);
  const second = historyItems([call]);
  const ids = [first[0]!.call_id, first[2]!.call_id, second[0]!.call_id];
  assert.equal(new Set(ids).size, 3);
  for (const id of ids) assert.match(id as string, /^call_[a-zA-Z0-9]{24}$/);
  assert.equal(first[0]!.call_id, first[1]!.call_id);
  assert.equal(first[2]!.call_id, first[3]!.call_id);
  assert.equal(second[0]!.call_id, second[1]!.call_id);
  assert.equal(first[0]!.arguments, '{"command":"true"}');
  assert.equal(first[1]!.output, '');
});

test('history.results applies text, shell exits, JSON, missing result and failure rules to both forms', () => {
  const cases: Array<{ call: ToolCall; expected: string }> = [
    { call: { type: 'tool_call', name: 'shell', input: { command: 'test' }, ok: true, result: 'exact\n' }, expected: 'exact\n' },
    { call: { type: 'tool_call', name: 'shell', input: { command: 'test' }, ok: true, result: { output: 'out', exitCode: 0 } }, expected: 'out' },
    { call: { type: 'tool_call', name: 'shell', input: { command: 'test' }, ok: false, result: { output: 'out', exitCode: 2, truncated: true }, error: 'failed' }, expected: 'out\nexit code: 2\nfailed' },
    { call: { type: 'tool_call', name: 'shell', input: { command: 'test' }, ok: false, result: { output: '', exitCode: -1 }, error: 'interrupted' }, expected: '\nexit code: -1\ninterrupted' },
    { call: { type: 'tool_call', name: 'Read', input: {}, ok: true, result: { text: 'cut' } }, expected: '{"text":"cut"}' },
    { call: { type: 'tool_call', name: 'Read', input: {}, ok: false, result: null, error: 'failed' }, expected: 'null\nfailed' },
    { call: { type: 'tool_call', name: 'Read', input: {}, ok: false, error: 'failed without result' }, expected: 'failed without result' },
    { call: { type: 'tool_call', name: 'Read', input: {}, ok: true }, expected: '' },
    { call: { type: 'tool_call', name: 'Read', input: {}, ok: true, result: false, error: 'ignored on success' }, expected: 'false' },
  ];
  for (const { call, expected } of cases) {
    assert.equal(toolResultText(call), expected);
    assert.equal(historyItems([call])[1]!.output, expected);
    assert.equal(labelledHistoryInput([call], { text: 'new' }).text,
      `Earlier conversation, for context:\n\n[Tool call: ${call.name}]\n${JSON.stringify(call.input)}\n[Tool ${call.ok ? 'result' : 'error'}]\n${expected}\n\nNew message:\n\nnew`);
  }
});

test('history.labelled uses contract headings and image counts, with earlier pictures before the new ones', () => {
  const currentPicture: Image = { mediaType: 'image/webp', data: 'aw==' };
  const fallback = labelledHistoryInput([
    { type: 'message', role: 'user', text: 'old user\n', images: [picture, otherPicture] },
    { type: 'message', role: 'assistant', text: 'old assistant', images: [otherPicture] },
    { type: 'tool_call', name: 'Read', input: { path: '/quoted "path"' }, ok: true, result: 'read result' },
    { type: 'tool_call', name: 'shell', input: { command: 'false', cwd: '/repository' }, ok: false,
      result: { output: 'output', exitCode: 1 }, error: 'failed' },
  ], { text: 'new text\n', images: [currentPicture] });
  assert.equal(fallback.text, 'Earlier conversation, for context:\n\n' +
    '[User]\nold user\n\n[Images: 2]\n' +
    '[Assistant]\nold assistant\n[Images: 1]\n' +
    '[Tool call: Read]\n{"path":"/quoted \\"path\\""}\n[Tool result]\nread result\n' +
    '[Tool call: shell]\n{"command":"false","cwd":"/repository"}\n[Tool error]\noutput\nexit code: 1\nfailed\n\n' +
    'New message:\n\nnew text\n');
  assert.deepEqual(fallback.images, [picture, otherPicture, otherPicture, currentPicture]);
});

test('history.images prepares private ordered local files for current and labelled inputs', async t => {
  const temporary = await mkdtemp(join(tmpdir(), 'syl88-images-'));
  t.after(async () => { await rm(temporary, { recursive: true, force: true }); });
  const currentPicture: Image = { mediaType: 'image/gif', data: 'AAECAw==' };
  const input = labelledHistoryInput([{ type: 'message', role: 'user', text: 'old', images: [picture, otherPicture] }],
    { text: 'new', images: [currentPicture] });
  const items = await prepareTurnInput(input, temporary);
  assert.deepEqual(items, [{ type: 'text', text: input.text },
    { type: 'localImage', path: join(temporary, 'image-0.png') },
    { type: 'localImage', path: join(temporary, 'image-1.jpg') },
    { type: 'localImage', path: join(temporary, 'image-2.gif') }]);
  for (const [index, image] of input.images.entries()) {
    const path = items[index + 1]!.path as string;
    assert.deepEqual(await readFile(path), Buffer.from(image.data, 'base64'));
    assert.equal((await stat(path)).mode & 0o777, 0o600);
  }
  assert.deepEqual(await readdir(temporary), ['image-0.png', 'image-1.jpg', 'image-2.gif']);
  assert.deepEqual(await prepareTurnInput({ text: 'text only' }, temporary), [{ type: 'text', text: 'text only' }]);
  await assert.rejects(prepareTurnInput({ text: 'cannot overwrite a previous picture', images: [picture] }, temporary), { code: 'EEXIST' });
});
