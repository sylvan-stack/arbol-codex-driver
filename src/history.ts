import { randomBytes } from 'node:crypto';
import { writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { isObject } from './settings.js';
import type { HistoryItem, Image } from './run-request.js';

type ToolCall = Extract<HistoryItem, { type: 'tool_call' }>;
type TurnInput = { text: string; images?: Image[] };

/** The same text form is used in native tool results and the labelled fallback. */
export function toolResultText(item: ToolCall): string {
  let text = '';
  if (typeof item.result === 'string') text = item.result;
  else if (item.result !== undefined) {
    if (item.name === 'shell' && isObject(item.result) && 'output' in item.result) {
      text = typeof item.result.output === 'string' ? item.result.output : JSON.stringify(item.result.output) ?? '';
      if (typeof item.result.exitCode === 'number' && item.result.exitCode !== 0) text += `\nexit code: ${item.result.exitCode}`;
    } else text = JSON.stringify(item.result) ?? '';
  }
  if (!item.ok && item.error) text += (text ? '\n' : '') + item.error;
  return text;
}

/** Raw Responses items accepted by the stable thread/inject_items request. */
export function historyItems(history: HistoryItem[]): Record<string, unknown>[] {
  const items: Record<string, unknown>[] = [];
  for (const item of history) {
    if (item.type === 'message') {
      items.push({ type: 'message', role: item.role, content: [
        { type: item.role === 'user' ? 'input_text' : 'output_text', text: item.text },
        ...(item.images ?? []).map(picture => ({ type: 'input_image', image_url: `data:${picture.mediaType};base64,${picture.data}` })),
      ] });
    } else {
      const callId = 'call_' + randomBytes(12).toString('hex');
      const input = item.name === 'shell' && isObject(item.input)
        ? { command: item.input.command, ...(item.input.cwd === undefined ? {} : { cwd: item.input.cwd }) }
        : item.input;
      items.push({ type: 'function_call', name: item.name, arguments: JSON.stringify(input), call_id: callId },
        { type: 'function_call_output', call_id: callId, output: toolResultText(item) });
    }
  }
  return items;
}

export function labelledHistoryInput(history: HistoryItem[], input: TurnInput): { text: string; images: Image[] } {
  const parts = ['Earlier conversation, for context:\n'];
  const images: Image[] = [];
  for (const item of history) {
    if (item.type === 'message') {
      parts.push(`[${item.role === 'user' ? 'User' : 'Assistant'}]\n${item.text}` +
        (item.images?.length ? `\n[Images: ${item.images.length}]` : ''));
      images.push(...(item.images ?? []));
    } else {
      parts.push(`[Tool call: ${item.name}]\n${JSON.stringify(item.input)}\n[Tool ${item.ok ? 'result' : 'error'}]\n${toolResultText(item)}`);
    }
  }
  return { text: parts.join('\n') + '\n\nNew message:\n\n' + input.text, images: [...images, ...(input.images ?? [])] };
}

/** The run owns the private folder and removes it after ending its app-server. */
export async function prepareTurnInput(input: TurnInput, temporary: string): Promise<Record<string, unknown>[]> {
  const message: Record<string, unknown>[] = [{ type: 'text', text: input.text }];
  const extension = { 'image/png': 'png', 'image/jpeg': 'jpg', 'image/webp': 'webp', 'image/gif': 'gif' };
  for (const [index, picture] of (input.images ?? []).entries()) {
    const path = join(temporary, `image-${index}.${extension[picture.mediaType]}`);
    await writeFile(path, Buffer.from(picture.data, 'base64'), { mode: 0o600, flag: 'wx' });
    message.push({ type: 'localImage', path });
  }
  return message;
}
