import { appendFile, mkdir, readFile, realpath, stat, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { randomUUID } from 'node:crypto';
import { createInterface } from 'node:readline';
import { spawn } from 'node:child_process';
import { Failure } from './errors.js';
import { isObject } from './settings.js';

// Shapes: codex-cli 0.159.2 initialize, account/model responses, thread/turn
// responses, agentMessage/commandExecution items and tokenUsage notifications
// in this recording. IDs, text, token counts, errors, omitted optional fields,
// model-effort rejection and output sizes below are synthetic test variants.
// Continuity RPC/item shapes: research/tool-probes-2026-10-05.md, the
// 6 October addendum "earlier messages for a new thread". Saved rollout
// contents, resume refusals, concurrent timings and failed histories here are
// synthetic; this fixture never invokes the vendor or claims live inference.
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
  const scenarios = ['C10', 'C11', 'C12', 'C13', 'C14', 'C15', 'C16', 'C17', 'C18', 'C19', 'C20', 'C33', 'C38', 'C40', 'C42', 'C43'];
  const parts = ['supported', 'success', 'plain', 'hold', 'malformed', 'text', 'structure', 'dropped-effort', 'fail', 'refuse', 'refuse-stderr', 'inject-refused', 'resume-gone', 'delayed-usage',
    'tool', 'subagent', 'subagent-finished', 'subagent-late', 'subagent-nested', 'turn-start-race', 'stubborn', 'background', 'linger', 'stopping', 'other-call'];
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
  let threadId = 'fixture-thread';
  const turnId = scenario === 'C14' ? randomUUID() : 'fixture-turn';
  const context = { threadId, turnId };
  const restoredUsage = (): void => notify('thread/tokenUsage/updated', { threadId, tokenUsage: {
    total: { totalTokens: 900, inputTokens: 700, outputTokens: 200 },
    last: { totalTokens: 300, inputTokens: 200, outputTokens: 100 }, modelContextWindow: 258400,
  } });
  let initialized = false;
  let configured = false;
  let threadParams: Record<string, unknown> | undefined;
  let historyItems: Record<string, unknown>[] = [];
  let savedPath: string | undefined;
  let resumed = false;
  let turnActive = false;
  let subagentActive = false;
  let grandchildActive = false;
  let heartbeat: ReturnType<typeof setInterval> | undefined;
  const childContext = { threadId: 'fixture-subagent-thread', turnId: 'fixture-subagent-turn' };
  const grandchildContext = { threadId: 'fixture-grandchild-thread', turnId: 'fixture-grandchild-turn' };
  const savedScenario = scenario === 'C14' || scenario === 'C38';
  // Stop envelopes and separate shell process groups are observed in the
  // 6 October stop addendum. Commands, PIDs, delayed results and stubborn
  // behavior are synthetic variants; this stand-in spends no vendor quota.
  const shellWorker = async (): Promise<{ shellPid: number; backgroundPid: number }> => {
    const marker = join(directory, 'worker-' + process.pid);
    const worker = spawn(process.execPath, ['-e', `
      const {spawn}=require('node:child_process');
      const {writeFileSync}=require('node:fs');
      const child=spawn(process.execPath,['-e','setInterval(()=>{},60000)'],{stdio:'ignore'});
      writeFileSync(${JSON.stringify(marker)},String(child.pid));
      setInterval(()=>{},60000);
    `], { detached: true, stdio: 'ignore' });
    worker.unref();
    await new Promise<void>((resolve, reject) => { worker.once('spawn', resolve); worker.once('error', reject); });
    let raw: string | undefined;
    for (let n = 0; n < 200 && !raw; n++) {
      raw = await readFile(marker, 'utf8').catch(() => undefined);
      if (!raw) await new Promise(resolve => setTimeout(resolve, 10));
    }
    if (!raw || !worker.pid) throw new Failure('internal', 'The stopping stand-in could not start its shell group.');
    return { shellPid: worker.pid, backgroundPid: Number(raw) };
  };
  const completedTurn = (thread: string, id: string, status: string): void => notify('turn/completed', {
    threadId: thread, turn: { id, items: [], itemsView: 'notLoaded', status, error: null },
  });
  const savedFile = (id: string): string => join(home, 'sessions', '2026', '10', '07', `rollout-2026-10-07T00-00-00-${id}.jsonl`);
  const persist = async (): Promise<void> => {
    if (!savedPath) return;
    await mkdir(join(home, 'sessions', '2026', '10', '07'), { recursive: true, mode: 0o700 });
    await writeFile(savedPath, JSON.stringify({ type: 'session_meta', payload: { id: threadId, cwd: threadParams!.cwd,
      fixtureParams: threadParams } }) + '\n' + historyItems.map(value => JSON.stringify({ type: 'response_item', payload: value }) + '\n').join(''), { mode: 0o600 });
  };
  const threadResult = (): Record<string, unknown> => {
    const params = threadParams!;
    return { thread: { id: threadId, sessionId: threadId, model: params.model, modelProvider: 'openai',
      reasoningEffort: part === 'dropped-effort' ? null : params.reasoningEffort ?? null,
      preview: '', ephemeral: params.ephemeral ?? false, cwd: params.cwd, status: { type: 'idle' }, turns: [], cliVersion: version, path: savedPath ?? null },
      model: params.model, modelProvider: 'openai', serviceTier: params.serviceTier ?? null, cwd: params.cwd,
      approvalPolicy: 'never', sandbox: { type: params.sandbox === 'read-only' ? 'readOnly' : 'dangerFullAccess',
        ...(params.sandbox === 'read-only' ? { networkAccess: false } : {}) }, reasoningEffort: part === 'dropped-effort' ? null : params.reasoningEffort ?? null };
  };
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
      if (savedScenario) { threadId = randomUUID(); context.threadId = threadId; }
      savedPath = params.ephemeral === true ? undefined : savedFile(threadId);
      await persist();
      const result = threadResult(); answer(result); notify('thread/started', { thread: result.thread });
    } else if (request.method === 'thread/resume') {
      if (!loggedIn || threadParams || typeof params.threadId !== 'string' || Object.keys(params).some(key => !['threadId', 'model'].includes(key)) ||
          params.model !== undefined && !modelIds.includes(String(params.model))) {
        error('Invalid thread resume configuration'); continue;
      }
      if (part === 'refuse' || part === 'refuse-stderr') {
        if (part === 'refuse-stderr') process.stderr.write('Synthetic thread resume refusal.\n');
        error('Synthetic thread resume refusal.', -32000); continue;
      }
      const raw = part === 'resume-gone' ? undefined : await readFile(savedFile(params.threadId), 'utf8').catch(() => undefined);
      if (!raw) { error(`no rollout found for thread id ${params.threadId}`, -32600); continue; }
      const records = raw.trim().split('\n').map(line => JSON.parse(line));
      threadParams = { ...records[0].payload.fixtureParams, ...(params.model === undefined ? {} : { model: params.model }) };
      threadId = params.threadId; context.threadId = threadId;
      historyItems = records.slice(1).map(record => record.payload); savedPath = savedFile(threadId); resumed = true;
      // Resume can report accumulated usage before this run's turn exists.
      // These counts belong to the saved conversation, never to the new run.
      if (part !== 'delayed-usage') restoredUsage();
      answer(threadResult());
    } else if (request.method === 'thread/inject_items') {
      if (!threadParams || resumed || params.threadId !== threadId || !Array.isArray(params.items) ||
          Object.keys(params).some(key => !['threadId', 'items'].includes(key))) { error('Invalid history injection request'); continue; }
      if (['refuse', 'refuse-stderr', 'inject-refused'].includes(part)) {
        if (part === 'refuse-stderr') process.stderr.write('Synthetic native history refusal.\n');
        error('Synthetic native history refusal.', -32601); continue;
      }
      let invalid = false;
      const ids = new Set<string>();
      for (const [index, value] of params.items.entries()) {
        if (!isObject(value)) { invalid = true; break; }
        if (value.type === 'message') {
          if (!['user', 'assistant'].includes(String(value.role)) || !Array.isArray(value.content) || !value.content.every(part => isObject(part) &&
            (value.role === 'user' && part.type === 'input_image' && typeof part.image_url === 'string' && /^data:image\/(png|jpeg|webp|gif);base64,/.test(part.image_url) ||
             part.type === (value.role === 'user' ? 'input_text' : 'output_text') && typeof part.text === 'string'))) invalid = true;
        } else if (value.type === 'function_call') {
          const result = params.items[index + 1];
          if (typeof value.name !== 'string' || typeof value.arguments !== 'string' || typeof value.call_id !== 'string' ||
              !/^call_[a-zA-Z0-9]{24}$/.test(value.call_id) || ids.has(value.call_id) || !isObject(result) ||
              result.type !== 'function_call_output' || result.call_id !== value.call_id || typeof result.output !== 'string') invalid = true;
          else { ids.add(value.call_id); try { JSON.parse(value.arguments); } catch { invalid = true; } }
        } else if (value.type !== 'function_call_output' || typeof value.call_id !== 'string' || !ids.has(value.call_id)) invalid = true;
      }
      if (invalid) { error('Invalid native history items'); continue; }
      historyItems.push(...params.items as Record<string, unknown>[]); await persist(); answer({});
    } else if (request.method === 'turn/start') {
      const readonly = resumed ? isObject(params.sandboxPolicy) && params.sandboxPolicy.type === 'readOnly' : threadParams?.sandbox === 'read-only';
      if (!threadParams || params.threadId !== threadId || !Array.isArray(params.input) || params.input.length < 1 || !isObject(params.input[0]) ||
          params.input[0].type !== 'text' || typeof params.input[0].text !== 'string' || params.approvalPolicy !== 'never' ||
          !isObject(params.sandboxPolicy) || params.sandboxPolicy.type !== (readonly ? 'readOnly' : 'dangerFullAccess') ||
          readonly && params.sandboxPolicy.networkAccess !== false || !modelIds.includes(String(params.model)) || !resumed && params.model !== threadParams.model ||
          params.summary !== 'detailed' || params.serviceTier !== undefined && params.serviceTier !== 'priority') {
        error('Invalid fresh turn configuration'); continue;
      }
      if (part === 'dropped-effort') { error('Requested effort was not applied'); continue; }
      if (!fixtureModels.find(model => model.id === params.model)?.supportedReasoningEfforts.some(option => option.reasoningEffort === params.effort)) {
        error('Invalid turn reasoning effort'); continue;
      }
      // Exercise restored usage arriving after the Driver drains resume's
      // startup queue, while it awaits the new turn/start result.
      if (resumed && part === 'delayed-usage') restoredUsage();
      const images: { path: string; data: string; mode: number }[] = [];
      for (const picture of params.input.slice(1)) {
        if (!isObject(picture) || picture.type !== 'localImage' || typeof picture.path !== 'string') throw new Failure('tool_failed', 'Invalid image input.');
        images.push({ path: picture.path, data: (await readFile(picture.path)).toString('base64'), mode: (await stat(picture.path)).mode & 0o777 });
      }
      const calls = historyItems.filter(item => item.type === 'function_call');
      const shell = calls.find(call => call.name === 'shell' && JSON.parse(String(call.arguments)).command === 'printf history-shell-output');
      const shellResult = shell && historyItems.find(item => item.type === 'function_call_output' && item.call_id === shell.call_id);
      const foreign = calls.find(call => call.name === 'foreign_tool' && JSON.parse(String(call.arguments)).value === 'foreign-input');
      const historyImages = historyItems.flatMap(item => item.type === 'message' && Array.isArray(item.content) ? item.content : [])
        .filter(part => isObject(part) && part.type === 'input_image').map(part => {
          const [, mediaType, data] = /^data:([^;]+);base64,(.*)$/.exec(part.image_url)!; return { mediaType, data };
        });
      const stopFixture = ['C15', 'C17'].includes(scenario!) || scenario === 'C38' && part === 'hold' || scenario === 'C33' && part === 'stopping';
      const workers = stopFixture && ['tool', 'subagent', 'subagent-finished', 'subagent-late', 'subagent-nested', 'turn-start-race', 'stubborn', 'background', 'linger', 'hold'].includes(part)
        ? await shellWorker() : undefined;
      await received({ stage: 'input', request, checks: { ...base.checks, input: request, configurationApplied: true, images,
        toolPid: process.pid, backgroundPid: workers?.backgroundPid, shellPid: workers?.shellPid, backgroundWasAlive: !!workers,
        savedPath: savedPath ?? null, ephemeral: threadParams.ephemeral === true, resumed,
        nativeShellCall: !!shell, nativeShellResult: shellResult?.output, nativeShellFailed: typeof shellResult?.output === 'string' && shellResult.output.endsWith('\nhistory-error'),
        nativeForeignCall: !!foreign && historyItems.some(item => item.type === 'function_call_output' && item.call_id === foreign.call_id && item.output === '{"value":"foreign-value"}'),
        historyImages, systemPrompt: threadParams.developerInstructions ?? '', nativeHistory: historyItems.length > 0,
        labelledHistory: params.input[0].text.startsWith('Earlier conversation, for context:') } });
      const turn = { id: turnId, items: [], itemsView: 'notLoaded', status: 'inProgress', error: null, startedAt: null, completedAt: null, durationMs: null };
      if (part === 'turn-start-race') {
        // The server can announce its accepted turn before the RPC reply.
        notify('turn/started', { threadId, turn }); turnActive = true;
        await received({ stage: 'accepted-turn', checks: { ...base.checks, threadId, turnId } });
        setTimeout(() => answer({ turn }), 150);
      } else { answer({ turn }); notify('turn/started', { threadId, turn }); turnActive = true; }
      const input = params.input[0].text;
      if (stopFixture) {
        notify('item/agentMessage/delta', { ...context, itemId: 'partial-answer', delta: 'partial' });
        usage(3, 2);
        if (workers) {
          // processId is the vendor's command handle, not an OS process ID.
          const shell = { ...command(false), processId: '48412', command: 'sleep 60', cwd: process.cwd() };
          if (part.startsWith('subagent')) {
            const activity = { type: 'subAgentActivity', id: 'subagent-started-fixture', kind: 'started',
              agentThreadId: childContext.threadId, agentPath: '/root/fixture-worker' };
            item('item/started', activity); item('item/completed', activity);
            notify('turn/started', { threadId: childContext.threadId, turn: { ...turn, id: childContext.turnId } });
            subagentActive = true;
            notify('item/started', { ...childContext, item: { ...shell, id: 'fixture-subcall' } });
            notify('item/agentMessage/delta', { ...childContext, itemId: 'subagent-answer', delta: 'child-only' });
            if (part === 'subagent-nested') {
              const nested = { ...activity, id: 'grandchild-started-fixture', agentThreadId: grandchildContext.threadId, agentPath: '/root/fixture-worker/nested' };
              notify('item/started', { ...childContext, item: nested }); notify('item/completed', { ...childContext, item: nested });
              notify('turn/started', { threadId: grandchildContext.threadId, turn: { ...turn, id: grandchildContext.turnId } }); grandchildActive = true;
              notify('item/started', { ...grandchildContext, item: { ...shell, id: 'fixture-grandcall' } });
              notify('item/agentMessage/delta', { ...grandchildContext, itemId: 'grandchild-answer', delta: 'grandchild-only' });
            }
            heartbeat = setInterval(() => { void received({ stage: 'subagent-tick', checks: { ...base.checks, active: true } }); }, 20);
            if (part === 'subagent-finished') {
              completedTurn(threadId, turnId, 'completed'); turnActive = false;
            }
            if (part === 'subagent-late') setTimeout(() => {
              notify('item/completed', { ...childContext, item: { ...shell, id: 'fixture-subcall', status: 'completed', exitCode: 0, aggregatedOutput: 'child-result' } });
              notify('item/completed', { ...childContext, item: message('subagent-answer', 'child-only') });
              completedTurn(childContext.threadId, childContext.turnId, 'completed'); subagentActive = false; clearInterval(heartbeat);
              const finished = { ...activity, id: 'subagent-completed-fixture', kind: 'completed' };
              item('item/started', finished); item('item/completed', finished);
            }, 250);
          } else {
            item('item/started', shell);
            if (['background', 'linger'].includes(part)) item('item/completed', { ...shell, status: 'completed', exitCode: 0, aggregatedOutput: 'background-started' });
          }
        } else if (part === 'other-call') item('item/started', { type: 'webSearch', id: 'fixture-other-call', query: 'synthetic unfinished search' });
        if (['background', 'linger', 'plain', 'other-call', 'subagent-late'].includes(part)) {
          text('fixture-answer', 'answer'); completedTurn(threadId, turnId, 'completed'); turnActive = false;
        }
        continue;
      }
      if (input === 'early-exit') { lines.close(); process.stdin.destroy(); return 1; }
      if (part === 'malformed') { process.stdout.write('{"method":\n'); continue; }
      if (input === 'unknown-request') output({ id: 'fixture-server-request', method: 'future/request', params: { ...context } });
      if (part === 'hold' || input === 'hold') await new Promise(resolve => setTimeout(resolve, 1200));
      if (scenario === 'C18' && input === 'slow') for (let n = 0; n < 32; n++) text('fixture-answer-' + n, 's'.repeat(64 * 1024));
      else text('fixture-answer', 'answer');
      if (scenario === 'C13') { usage(3, 2); usage(7, 5, 4, 3); usage(7, 5, 4, 3); }
      if (scenario === 'C42' || scenario === 'C14') usage(3, 2);
      if (['C11', 'C20', 'C42'].includes(scenario!)) {
        const search = scenario === 'C20' && part === 'structure' ? { type: 'webSearch', id: 'fixture-call', query: '', action: null, results: null } : undefined;
        item('item/started', search ?? command(false));
        if (scenario === 'C42') { lines.close(); process.stdin.destroy(); return 1; }
        const result = scenario === 'C20' ? '😀'.repeat(60000) : 'fixture-output';
        item('item/completed', search ? { ...search, query: 'fixture', action: { type: 'search', query: 'fixture', queries: null },
          results: [{ type: 'text_result', domain: 'example.invalid', ref_id: 'fixture-result', snippet: result, title: 'Fixture', url: 'https://example.invalid/' }] } : command(true, result));
        text('fixture-after-tool', 'after-tool');
      }
      const failed = scenario === 'C12' || part === 'fail' || input === 'fail';
      if (savedScenario) {
        historyItems.push({ type: 'message', role: 'user', content: [{ type: 'input_text', text: input },
          ...images.map(image => ({ type: 'input_image', image_url: `data:image/${image.path.split('.').at(-1) === 'jpg' ? 'jpeg' : image.path.split('.').at(-1)};base64,${image.data}` }))] },
          { type: 'message', role: 'assistant', content: [{ type: 'output_text', text: 'answer' }] });
        await persist();
      }
      const finish = (): void => { turnActive = false; notify('turn/completed', { threadId, turn: { ...turn, status: failed ? 'failed' : 'completed', itemsView: 'summary',
        error: failed ? { message: 'Synthetic vendor failure.', codexErrorInfo: 'other', additionalDetails: null } : null } }); };
      if (input === 'unknown-request') setTimeout(finish, 75); else finish();
    } else if (request.method === 'turn/interrupt') {
      await received({ stage: 'interrupt', request, checks: { ...base.checks, input: request } });
      const main = params.threadId === threadId && params.turnId === turnId && turnActive;
      const child = params.threadId === childContext.threadId && params.turnId === childContext.turnId && subagentActive;
      const grandchild = params.threadId === grandchildContext.threadId && params.turnId === grandchildContext.turnId && grandchildActive;
      // The installed tool does not answer interrupts for an ended turn.
      if (!main && !child && !grandchild) continue;
      if (part === 'stubborn') continue;
      answer({});
      completedTurn(String(params.threadId), String(params.turnId), 'interrupted');
      if (main) turnActive = false;
      if (child) { subagentActive = false; clearInterval(heartbeat); }
      if (grandchild) grandchildActive = false;
    } else error('This stand-in implements only run app-server requests.', -32601);
  }
  clearInterval(heartbeat);
  if (part === 'linger') await new Promise<void>(() => { setInterval(() => {}, 60000); });
  return 0;
}
