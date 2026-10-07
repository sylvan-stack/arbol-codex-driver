import { randomUUID } from 'node:crypto';
import { readFile, realpath, stat } from 'node:fs/promises';
import { isAbsolute } from 'node:path';
import { Failure } from './errors.js';
import { isObject } from './settings.js';
import type { DriverSettings } from './settings.js';

export interface Image {
  mediaType: 'image/png' | 'image/jpeg' | 'image/webp' | 'image/gif';
  data: string;
}
export interface Message { role: 'user' | 'assistant'; text: string; images?: Image[] }
export type HistoryItem = ({ type: 'message' } & Message)
  | { type: 'tool_call'; name: string; input: unknown; ok: boolean; result?: unknown; error?: string };
export interface RunLimits { idleSeconds?: number; totalSeconds?: number }
export interface RunRequest {
  runId: string;
  subscriptionId: string;
  model?: string | undefined;
  effort?: string | undefined;
  effortFromSettings: boolean;
  serviceTier?: string | undefined;
  systemPrompt?: string | undefined;
  workingDirectory?: string | undefined;
  additionalDirectories: string[];
  history: HistoryItem[];
  input: { role: 'user'; text: string; images?: Image[] };
  chatSessionId?: string | undefined;
  tools: 'all' | 'none';
  limits?: RunLimits | undefined;
  searchPath: string[];
  labels?: Record<string, string> | undefined;
  control: boolean;
  output: 'events' | 'text';
}
export interface RunRequestContext {
  settings?: DriverSettings;
  message?: string;
  firstLine?: () => Promise<string>;
  identity?: (runId: string, labels: Record<string, string> | undefined) => void;
}

export async function readRunRequest(options: Record<string, string | boolean | string[]>,
  context: RunRequestContext = {}): Promise<RunRequest> {
  const bad = (message: string): never => { throw new Failure('invalid_input', message); };
  const optionString = (name: string): string | undefined => {
    const value = options[name];
    if (value === undefined) return undefined;
    return typeof value === 'string' && value.length > 0 ? value : bad(`Option --${name} needs a value.`);
  };
  const repeat = (name: string): string[] => {
    const value = options[name];
    if (value === undefined) return [];
    const values = typeof value === 'string' ? [value] : value;
    if (!Array.isArray(values) || !values.every(item => typeof item === 'string' && item.length > 0)) {
      bad(`Option --${name} needs a value.`);
    }
    return values as string[];
  };
  let value: Record<string, unknown> = {};
  const file = optionString('request');
  if (file !== undefined) {
    let input: unknown;
    try {
      if (file === '-' && context.firstLine === undefined) bad('The request line is missing.');
      input = JSON.parse(file === '-' ? await context.firstLine!() : await readFile(file, 'utf8'));
    } catch { bad('The request could not be read as JSON.'); }
    if (!isObject(input)) bad('The request must be a JSON object.');
    value = { ...input as Record<string, unknown> };
  }
  for (const [option, field] of Object.entries({ subscription: 'subscriptionId', model: 'model', effort: 'effort',
    'service-tier': 'serviceTier', cwd: 'workingDirectory', tools: 'tools', 'chat-session': 'chatSessionId', 'run-id': 'runId' })) {
    const replacement = optionString(option);
    if (replacement !== undefined) value[field] = replacement;
  }
  const promptFile = optionString('system-prompt-file');
  if (promptFile !== undefined) {
    try { value.systemPrompt = await readFile(promptFile, 'utf8'); }
    catch { bad('The system prompt file could not be read.'); }
  }
  if (context.message !== undefined) {
    value.input = { ...(isObject(value.input) ? value.input : {}), role: 'user', text: context.message };
  }
  if (options['add-dir'] !== undefined) value.additionalDirectories = repeat('add-dir');
  if (options.label !== undefined) {
    const labels: Record<string, unknown> = { ...(isObject(value.labels) ? value.labels : {}) };
    for (const label of repeat('label')) {
      const equal = label.indexOf('=');
      if (equal <= 0) bad('A label must be key=value.');
      Object.defineProperty(labels, label.slice(0, equal), {
        value: label.slice(equal + 1), enumerable: true, configurable: true, writable: true,
      });
    }
    value.labels = labels;
  }
  for (const field of ['runId', 'subscriptionId', 'model', 'effort', 'serviceTier', 'workingDirectory', 'chatSessionId']) {
    if (value[field] !== undefined && (typeof value[field] !== 'string' || !value[field])) bad(`Invalid request field ${field}.`);
  }
  if (value.systemPrompt !== undefined && typeof value.systemPrompt !== 'string') bad('Invalid systemPrompt.');
  const settings = context.settings ?? {};
  const subscriptionId = value.subscriptionId as string ?? settings.defaultSubscription ?? 'chatgpt';
  const defaults = settings.subscriptions?.[subscriptionId];
  const runId = value.runId as string ?? randomUUID();
  if (!/^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$/.test(runId)) bad('The run identifier is not a safe file name.');
  if (value.labels !== undefined && (!isObject(value.labels) || !Object.values(value.labels).every(item => typeof item === 'string'))) {
    bad('Labels must be a string mapping.');
  }
  const labels = value.labels as Record<string, string> | undefined;
  // Keep valid caller identity on refusals of the rest of the request, too.
  context.identity?.(runId, labels);
  const tools = value.tools ?? (file === undefined ? 'none' : undefined);
  if (tools !== 'all' && tools !== 'none') bad('The request must name tools as all or none.');
  const history = value.history ?? (file === undefined ? [] : undefined);
  if (!Array.isArray(history)) bad('The request must contain a history array.');
  const validImages = (images: unknown): boolean => images === undefined || Array.isArray(images) && images.every(image =>
    isObject(image) && ['image/png', 'image/jpeg', 'image/webp', 'image/gif'].includes(image.mediaType as string) &&
    typeof image.data === 'string' && image.data.length > 0 && image.data.length % 4 === 0 &&
    /^[A-Za-z0-9+/]*={0,2}$/.test(image.data));
  for (const entry of history as unknown[]) {
    if (!isObject(entry)) bad('Each history item must be an object.');
    const item = entry as Record<string, unknown>;
    if (item.type === 'message') {
      if (!['user', 'assistant'].includes(item.role as string) || typeof item.text !== 'string' || !validImages(item.images)) {
        bad('Invalid history message.');
      }
    } else if (item.type === 'tool_call') {
      if (typeof item.name !== 'string' || !item.name || !('input' in item) || typeof item.ok !== 'boolean' ||
        item.error !== undefined && typeof item.error !== 'string') bad('Invalid history tool call.');
      if (item.name === 'shell' && (!isObject(item.input) || typeof item.input.command !== 'string')) {
        bad('A shell history call needs a command.');
      }
    } else bad('Unknown history item type.');
  }
  if (!isObject(value.input) || value.input.role !== 'user' || typeof value.input.text !== 'string') {
    bad('The input must be a user message with text.');
  }
  const input = value.input as RunRequest['input'];
  if (!validImages(input.images)) bad('Images must have supported media types and base64 data.');
  const paths = (field: string): string[] => {
    const list = value[field] ?? [];
    if (!Array.isArray(list) || !list.every(item => typeof item === 'string' && isAbsolute(item))) {
      bad(`${field} must contain absolute paths.`);
    }
    return list as string[];
  };
  const additionalDirectories = paths('additionalDirectories');
  const searchPath = paths('searchPath');
  let workingDirectory = value.workingDirectory as string | undefined;
  if (workingDirectory === undefined && tools === 'all') bad('A run with tools needs a working directory.');
  for (const directory of [...(workingDirectory === undefined ? [] : [workingDirectory]), ...additionalDirectories]) {
    if (!isAbsolute(directory) || !await stat(directory).then(info => info.isDirectory()).catch(() => false)) {
      bad('A working or additional directory does not exist.');
    }
  }
  if (workingDirectory !== undefined) {
    try { workingDirectory = await realpath(workingDirectory); }
    catch { bad('The working directory could not be resolved.'); }
  }
  if (value.limits !== undefined && (!isObject(value.limits) || Object.entries(value.limits).some(([key, limit]) =>
    !['idleSeconds', 'totalSeconds'].includes(key) || typeof limit !== 'number' || !Number.isFinite(limit) || limit < 0))) {
    bad('Invalid run limits.');
  }
  if (options.control !== undefined && typeof options.control !== 'boolean') bad('Option --control takes no value.');
  const output = optionString('output') ?? 'events';
  if (output !== 'events' && output !== 'text') bad('Output must be events or text.');
  return { runId, subscriptionId, model: value.model as string ?? defaults?.defaultModel,
    effort: value.effort as string ?? defaults?.defaultEffort,
    effortFromSettings: value.effort === undefined && defaults?.defaultEffort !== undefined,
    serviceTier: value.serviceTier as string | undefined,
    systemPrompt: value.systemPrompt as string | undefined, workingDirectory, additionalDirectories,
    history: history as HistoryItem[], input, chatSessionId: value.chatSessionId as string | undefined,
    tools: tools as RunRequest['tools'], limits: value.limits as RunLimits | undefined, searchPath, labels,
    control: options.control === true, output: output as RunRequest['output'] };
}
