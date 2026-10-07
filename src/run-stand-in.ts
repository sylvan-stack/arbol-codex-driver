import { appendFile, readFile, realpath, stat, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { createInterface } from 'node:readline';
import { Failure } from './errors.js';
import { isObject } from './settings.js';

// Shapes: codex-cli 0.159.2 initialize, account/model responses, thread/turn
// responses, agentMessage/commandExecution items and tokenUsage notifications
// in this recording. IDs, text, token counts, errors, omitted optional fields,
// model-effort rejection and output sizes below are synthetic test variants.
const source = '~/Artifacts/arbol-codex-driver/research/probe-scripts-2026-10-06/live/codex-all.json';
const version = '0.159.2';
const modelIds = ['gpt-6.1-sol', 'gpt-6-astra'];
const fixtureModels = modelIds.map((id, index) => ({
  id, model: id, displayName: index === 0 ? 'GPT-6.1-Sol' : 'GPT-6-Astra', hidden: false,
  supportedReasoningEfforts: ['low', 'medium', 'high', 'xhigh', 'max', 'ultra'].map(reasoningEffort => ({ reasoningEffort, description: 'Fixture effort' })),
  defaultReasoningEffort: index === 0 ? 'low' : 'medium',
  serviceTiers: [{ id: 'priority', name: 'Fast', description: 'Fixture priority tier' }], isDefault: index === 0,
}));

export async function runStandIn(directory: string, args: string[]): Promise<number> {
  const [scenario, part = 'plain', ...extra] = (await readFile(join(directory, 'scenario'), 'utf8')).trim().split(/\s+/);
  const scenarios = ['C10', 'C11', 'C12', 'C13', 'C18', 'C19', 'C20', 'C33', 'C40', 'C42', 'C43'];
  const parts = ['supported', 'success', 'plain', 'hold', 'malformed', 'text', 'structure', 'dropped-effort'];
  if (extra.length || !scenarios.includes(scenario!) || !parts.includes(part)) throw new Failure('invalid_input', 'This stand-in does not implement that run scenario.');
  const home = process.env.CODEX_HOME;
  const base = {
    scenario, part, arguments: args, environment: Object.keys(process.env).sort(), workingDirectory: process.cwd(), toolVersion: version,
    checks: { source, synthetic: 'Input, tokens, omitted fields, model-effort rejection, failure and oversized-output variants',
      home: home ?? null,
      privateHome: !!home && await stat(home).then(value => (value.mode & 0o077) === 0).catch(() => false),
      injectedVariablesAbsent: Object.keys(process.env).every(name => !name.startsWith('OPENAI_') && (!name.startsWith('CODEX_') || name === 'CODEX_HOME') &&
        !['ANTHROPIC_API_KEY', 'CLAUDECODE', 'CLAUDE_SESSION_ID', 'NODE_OPTIONS'].includes(name)),
    },
  };
  const received = async (details: Record<string, unknown> = {}) => appendFile(join(directory, 'received.jsonl'), JSON.stringify({ ...base, ...details }) + '\n', { mode: 0o600 });
  await received();
  if (args.length === 1 && args[0] === '--version') { process.stdout.write(`codex-cli ${version}\n`); return 0; }
  if (args.length !== 1 || args[0] !== 'app-server' || !home) throw new Failure('unsupported', 'This stand-in requires app-server and a Subscription home.');
  const credential = join(home, 'auth.json');
  let loggedIn = await stat(credential).then(() => true).catch(() => false);
  const config = await readFile(join(home, 'config.toml'), 'utf8');
  if (!base.checks.privateHome || !base.checks.injectedVariablesAbsent ||
      !/check_for_update_on_startup\s*=\s*false/.test(config) || !/web_search\s*=\s*"live"/.test(config) ||
      !/cli_auth_credentials_store\s*=\s*"file"/.test(config) || !/\[analytics\]\s*enabled\s*=\s*false/.test(config) ||
      !/\[features\]\s*memories\s*=\s*false/.test(config)) throw new Failure('tool_failed', 'The run stand-in requires the isolated Driver environment and configuration.');
  const output = (value: unknown): void => { process.stdout.write(JSON.stringify(value) + '\n'); };
  const notify = (method: string, params: unknown): void => output({ method, params, emittedAtMs: Date.now() });
  const threadId = 'fixture-thread';
  const turnId = 'fixture-turn';
  const context = { threadId, turnId };
  let initialized = false;
  let configured = false;
  let threadParams: Record<string, unknown> | undefined;
  const item = (method: string, value: unknown): void => notify(method, { ...context, item: value });
  const message = (id: string, value: string): Record<string, unknown> => ({ type: 'agentMessage', id, text: value, phase: 'final_answer', memoryCitation: null, delivery: null, questions: null });
  const text = (id: string, value: string): void => {
    item('item/started', message(id, ''));
    notify('item/agentMessage/delta', { ...context, itemId: id, delta: value.slice(0, 2) });
    item('item/completed', message(id, value));
  };
  const usage = (inputTokens: number, outputTokens: number, lastInput = inputTokens, lastOutput = outputTokens): void => notify('thread/tokenUsage/updated', {
    ...context, tokenUsage: { total: { totalTokens: inputTokens + outputTokens, inputTokens, outputTokens },
      last: { totalTokens: lastInput + lastOutput, inputTokens: lastInput, outputTokens: lastOutput }, modelContextWindow: 258400 },
  });
  const command = (completed: boolean, outputValue: string | null = null): Record<string, unknown> => ({
    type: 'commandExecution', id: 'fixture-call', pluginId: null, scriptPath: null, command: 'printf fixture-output',
    cwd: process.cwd(), processId: '12345', source: 'unifiedExecStartup', status: completed ? 'completed' : 'inProgress',
    commandActions: [{ type: 'unknown', command: 'printf fixture-output' }], aggregatedOutput: outputValue,
    exitCode: completed ? 0 : null, durationMs: completed ? 0 : null,
  });
  const lines = createInterface({ input: process.stdin });
  for await (const line of lines) {
    const request: unknown = JSON.parse(line);
    if (!isObject(request)) continue;
    const params = isObject(request.params) ? request.params : {};
    if (request.method !== 'turn/start') await received({ stage: request.method === undefined ? 'response' : 'request', request, checks: { ...base.checks, input: request, configurationApplied: true } });
    if (request.method === undefined) continue;
    if (!('id' in request)) continue;
    const answer = (result: unknown): void => output({ id: request.id, result });
    const error = (message: string, code = -32602): void => output({ id: request.id, error: { code, message } });
    if (request.method === 'initialize' && !initialized) {
      if (!isObject(params.clientInfo) || params.clientInfo.name !== 'arbol-codex-driver' || typeof params.clientInfo.version !== 'string') { error('Invalid initialize client identity'); continue; }
      initialized = true;
      answer({ userAgent: `arbol-codex-driver/${version} (Mac OS 27.0.1; arm64) unknown (arbol-codex-driver; 1.0.0)`, codexHome: home, platformFamily: 'unix', platformOs: 'macos' });
    } else if (!initialized) error('Not initialized');
    else if (request.method === 'config/read') {
      configured = true;
      answer({ config: { check_for_update_on_startup: false, web_search: 'live', cli_auth_credentials_store: 'file', analytics: { enabled: false }, features: { memories: false } }, origins: {}, layers: null });
    } else if (!configured) error('Driver configuration was not checked');
    else if (request.method === 'account/read') answer({ account: loggedIn ? { type: 'chatgpt', email: 'fixture@example.invalid', planType: 'fixture' } : null, requiresOpenaiAuth: true });
    else if (request.method === 'account/login/start') {
      answer({ type: 'chatgpt', loginId: 'fixture-login', authUrl: 'https://auth.openai.com/oauth/authorize?redirect_uri=http%3A%2F%2F127.0.0.1%3A1455%2Fauth%2Fcallback&state=fixture' });
      await writeFile(credential, JSON.stringify({ credential: 'fixture-vendor-secret' }), { mode: 0o600 }); loggedIn = true;
      notify('account/login/completed', { loginId: 'fixture-login', success: true, error: null, onboardingEntrypoint: null });
      notify('account/updated', { authMode: 'chatgpt', planType: 'fixture' });
    } else if (request.method === 'model/list') {
      if (params.includeHidden !== undefined && params.includeHidden !== false || params.cursor !== undefined && params.cursor !== null) { error('Invalid model list request'); continue; }
      answer({ data: fixtureModels, nextCursor: null });
    } else if (request.method === 'thread/start') {
      const sameDirectory = typeof params.cwd === 'string' && await Promise.all([realpath(params.cwd), realpath(process.cwd())])
        .then(([requested, actual]) => requested === actual, () => false);
      if (!loggedIn || threadParams || !modelIds.includes(String(params.model)) || !sameDirectory || params.approvalPolicy !== 'never' ||
          !['read-only', 'danger-full-access'].includes(String(params.sandbox)) || params.ephemeral !== undefined && typeof params.ephemeral !== 'boolean' ||
          params.developerInstructions !== undefined && typeof params.developerInstructions !== 'string') {
        error('Invalid fresh thread configuration'); continue;
      }
      threadParams = params;
      const thread = { id: threadId, sessionId: threadId, model: params.model, modelProvider: 'openai', reasoningEffort: part === 'dropped-effort' ? null : params.reasoningEffort ?? null,
        preview: '', ephemeral: params.ephemeral ?? false, cwd: params.cwd, status: { type: 'idle' }, turns: [], cliVersion: version, path: null };
      answer({ thread, model: params.model, modelProvider: 'openai', serviceTier: params.serviceTier ?? null, cwd: params.cwd,
        approvalPolicy: 'never', sandbox: { type: params.sandbox === 'read-only' ? 'readOnly' : 'dangerFullAccess', ...(params.sandbox === 'read-only' ? { networkAccess: false } : {}) },
        reasoningEffort: part === 'dropped-effort' ? null : params.reasoningEffort ?? null });
      notify('thread/started', { thread });
    } else if (request.method === 'turn/start') {
      const readonly = threadParams?.sandbox === 'read-only';
      if (!threadParams || params.threadId !== threadId || !Array.isArray(params.input) || params.input.length < 1 || !isObject(params.input[0]) ||
          params.input[0].type !== 'text' || typeof params.input[0].text !== 'string' || params.approvalPolicy !== 'never' ||
          !isObject(params.sandboxPolicy) || params.sandboxPolicy.type !== (readonly ? 'readOnly' : 'dangerFullAccess') ||
          readonly && params.sandboxPolicy.networkAccess !== false || params.model !== threadParams.model ||
          params.summary !== 'detailed' || params.serviceTier !== undefined && params.serviceTier !== 'priority') {
        error('Invalid fresh turn configuration'); continue;
      }
      if (part === 'dropped-effort') { error('Requested effort was not applied'); continue; }
      if (!fixtureModels.find(model => model.id === params.model)?.supportedReasoningEfforts.some(option => option.reasoningEffort === params.effort)) {
        error('Invalid turn reasoning effort'); continue;
      }
      const images: { path: string; data: string; mode: number }[] = [];
      for (const picture of params.input.slice(1)) {
        if (!isObject(picture) || picture.type !== 'localImage' || typeof picture.path !== 'string') throw new Failure('tool_failed', 'Invalid image input.');
        images.push({ path: picture.path, data: (await readFile(picture.path)).toString('base64'), mode: (await stat(picture.path)).mode & 0o777 });
      }
      await received({ stage: 'input', request, checks: { ...base.checks, input: request, configurationApplied: true, images } });
      const turn = { id: turnId, items: [], itemsView: 'notLoaded', status: 'inProgress', error: null, startedAt: null, completedAt: null, durationMs: null };
      answer({ turn }); notify('turn/started', { threadId, turn });
      const input = params.input[0].text;
      if (input === 'early-exit') { lines.close(); process.stdin.destroy(); return 1; }
      if (part === 'malformed') { process.stdout.write('{"method":\n'); continue; }
      if (input === 'unknown-request') output({ id: 'fixture-server-request', method: 'future/request', params: { ...context } });
      if (part === 'hold' || input === 'hold') await new Promise(resolve => setTimeout(resolve, 1200));
      if (scenario === 'C18' && input === 'slow') for (let n = 0; n < 32; n++) text('fixture-answer-' + n, 's'.repeat(64 * 1024));
      else text('fixture-answer', 'answer');
      if (scenario === 'C13') { usage(3, 2); usage(7, 5, 4, 3); usage(7, 5, 4, 3); }
      if (scenario === 'C42') usage(3, 2);
      if (['C11', 'C20', 'C42'].includes(scenario!)) {
        const search = scenario === 'C20' && part === 'structure' ? { type: 'webSearch', id: 'fixture-call', query: '', action: null, results: null } : undefined;
        item('item/started', search ?? command(false));
        if (scenario === 'C42') { lines.close(); process.stdin.destroy(); return 1; }
        const result = scenario === 'C20' ? '😀'.repeat(60000) : 'fixture-output';
        item('item/completed', search ? { ...search, query: 'fixture', action: { type: 'search', query: 'fixture', queries: null },
          results: [{ type: 'text_result', domain: 'example.invalid', ref_id: 'fixture-result', snippet: result, title: 'Fixture', url: 'https://example.invalid/' }] } : command(true, result));
        text('fixture-after-tool', 'after-tool');
      }
      const failed = scenario === 'C12' || input === 'fail';
      const finish = (): void => notify('turn/completed', { threadId, turn: { ...turn, status: failed ? 'failed' : 'completed', itemsView: 'summary',
        error: failed ? { message: 'Synthetic vendor failure.', codexErrorInfo: 'other', additionalDetails: null } : null } });
      if (input === 'unknown-request') setTimeout(finish, 75); else finish();
    } else error('This stand-in implements only fresh-run app-server requests.', -32601);
  }
  return 0;
}
