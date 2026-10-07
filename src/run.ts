import { createInterface } from 'node:readline';
import { realpath, rm } from 'node:fs/promises';
import { delimiter, join } from 'node:path';
import { AppServer } from './app-server.js';
import { normalizeAccount, readModelCatalog } from './catalog.js';
import { Chats, MessageDigest } from './continuity.js';
import type { ContinuityPlan } from './continuity.js';
import { Failure } from './errors.js';
import { EventStream } from './event-stream.js';
import { historyItems, labelledHistoryInput, prepareTurnInput } from './history.js';
import { RunEvents } from './run-events.js';
import { readRunRequest } from './run-request.js';
import type { RunRequest } from './run-request.js';
import { Runs } from './runs.js';
import { isObject } from './settings.js';
import { fixedWait, privateDirectory, readJson, writeJson } from './state.js';
import { inspectTool, requireTool } from './tool.js';
import type { Command } from './arguments.js';
import type { Subscriptions } from './subscriptions.js';
import type { ProcessEnv } from './types.js';

/** Interrupt all known turns under one deadline; late child starts join that stop. */
async function interruptTurns(server: AppServer, mapper: RunEvents, deadline: number): Promise<void> {
  const sent = new Set<string>();
  const pending: Promise<unknown>[] = [];
  const cancellation = new AbortController();
  const timer = setTimeout(() => cancellation.abort(), Math.max(1, deadline - performance.now()));
  try {
    for (const notification of server.takeNotifications()) mapper.consume(notification.method, notification.params);
    while (performance.now() < deadline) {
      for (const turn of mapper.activeTurns) {
        const key = turn.threadId + ':' + turn.turnId;
        if (sent.has(key)) continue;
        sent.add(key);
        pending.push(server.request('turn/interrupt', turn, { signal: cancellation.signal }).catch(() => {}));
      }
      if (!mapper.activeTurns.length && !mapper.hasActiveAgents) break;
      const notification = await server.nextNotification({ signal: cancellation.signal }).catch(() => undefined);
      if (!notification) break;
      mapper.consume(notification.method, notification.params);
    }
  } finally {
    cancellation.abort(); clearTimeout(timer); await Promise.allSettled(pending);
  }
}

export async function run(command: Command, subscriptions: Subscriptions, events: EventStream,
  env: ProcessEnv, build: string, signal: AbortSignal): Promise<number> {
  const input = command.options.request === '-' || command.options.control ? createInterface({ input: process.stdin, crlfDelay: Infinity }) : undefined;
  const lines = input?.[Symbol.asyncIterator]();
  let server: AppServer | undefined;
  let mapper: RunEvents | undefined;
  let error: unknown;
  let temporary: string | undefined;
  let reservedId: string | undefined;
  let controlTask: Promise<void> | undefined;
  let settled = false;
  let started = false;
  let request: RunRequest | undefined;
  let plan: ContinuityPlan | undefined;
  let conversation: string | undefined;
  let currentModel: string | undefined;
  let stopAt: number | undefined;
  const fingerprint = new MessageDigest();
  const chats = new Chats(subscriptions.state);
  const pendingNotices: Array<Record<string, unknown>> = [];
  const localStop = new AbortController();
  const activeSignal = AbortSignal.any([signal, localStop.signal]);
  const markStop = (): void => { stopAt ??= performance.now(); input?.close(); };
  activeSignal.addEventListener('abort', markStop, { once: true });
  if (activeSignal.aborted) markStop();
  const outputClosed = (): void => localStop.abort();
  events.output.on('error', outputClosed);
  const runs = new Runs(subscriptions.state);
  try {
    const parsed = await readRunRequest(command.options, { settings: subscriptions.settings,
      ...(command.positionals[0] === undefined ? {} : { message: command.positionals[0] }),
      firstLine: async () => {
        activeSignal.throwIfAborted();
        const line = await lines!.next();
        activeSignal.throwIfAborted();
        if (line.done) {
          if (command.options.control) localStop.abort();
          throw new Failure('invalid_input', 'The request line is missing.');
        }
        return line.value;
      }, identity: (runId, labels) => { events.runId = runId; events.labels = labels; } });
    request = parsed;
    events.textOnly = request.output === 'text';
    await runs.list();
    for (const item of request.history) fingerprint.add(item);
    fingerprint.add({ ...request.input, type: 'message' });
    if (!request.control) input?.close();
    const subscription = await subscriptions.requireSignedIn(request.subscriptionId);
    const record = await subscriptions.state.withSubscriptionLock(subscription.id, async () => {
      const current = await subscriptions.record(subscription.id);
      if (current.state !== 'signed_in') throw new Failure('not_signed_in', 'Sign in to this Subscription first.');
      if (await readJson(join(subscriptions.state.subscription(subscription.id), 'sign-in.json')) !== undefined) throw new Failure('in_use', 'An account operation is still in progress.');
      const record = await runs.reserve({ runId: parsed.runId, subscriptionId: parsed.subscriptionId,
        ...(parsed.labels === undefined ? {} : { labels: parsed.labels }),
        ...(parsed.chatSessionId === undefined ? {} : { chatSessionId: parsed.chatSessionId }) });
      reservedId = parsed.runId;
      plan = await chats.select(parsed, join(subscriptions.state.subscription(subscription.id), 'home'));
      if (plan.conversation !== undefined) record.conversation = plan.conversation;
      if (plan.continuedConversation !== undefined) record.continuedConversation = plan.continuedConversation;
      await runs.save(record);
      return record;
    }, env);
    reservedId = request.runId;
    temporary = join(subscriptions.state.directory, 'tmp', request.runId);
    await privateDirectory(temporary);
    const work = request.workingDirectory ?? join(temporary, 'work');
    if (request.workingDirectory === undefined) await privateDirectory(work);
    const cwd = await realpath(work);
    const childEnv = { ...env };
    if (request.searchPath.length) childEnv.PATH = (childEnv.PATH ?? '') + delimiter + request.searchPath.join(delimiter);
    if (request.control) controlTask = (async () => {
      for await (const line of { [Symbol.asyncIterator]: () => lines! }) {
        let value: unknown;
        try { value = JSON.parse(line); } catch { /* Refusal below. */ }
        if (isObject(value) && value.type === 'stop' && Object.keys(value).length === 1) { localStop.abort(); return; }
        events.emit('control_refused', { error: new Failure(isObject(value) && value.type === 'answer' ? 'not_found' : 'invalid_input',
          isObject(value) && value.type === 'answer' ? 'That question is not open.' : 'This control line is not accepted.').result,
          ...(isObject(value) && typeof value.askId === 'string' ? { askId: value.askId } : {}) });
      }
      if (!settled) localStop.abort();
    })().catch(() => { if (!settled) localStop.abort(); });
    const tool = await inspectTool(subscriptions.state, subscriptions.settings.toolPath, env, activeSignal); requireTool(tool);
    server = await AppServer.start({ toolPath: tool.path!, home: join(subscriptions.state.subscription(subscription.id), 'home'),
      cwd, env: childEnv, signal: activeSignal, requestTimeoutMs: fixedWait(30000, env),
      launchIdentityPath: join(temporary, 'tool-owner.txt'),
      onSpawn: async owner => { record.tool = owner; await runs.save(record); },
      onServerRequest: (method, _params) => {
        const notice = { code: 'unexpected_request', message: `codex sent ${method}; there is nobody to answer a question in this run.` };
        if (started) events.emit('notice', notice); else pendingNotices.push(notice);
        if (method === 'item/commandExecution/requestApproval' || method === 'item/fileChange/requestApproval') return { decision: 'accept' };
        return undefined;
      } });
    const account = normalizeAccount(await server.request('account/read', {}, { signal: activeSignal }));
    if (!account) {
      await subscriptions.runReport(subscription, new Failure('credential_rejected', 'The Codex home has no ChatGPT account.', { remedy: 'Sign in again.' }).result);
      throw new Failure('not_signed_in', 'The Codex home has no ChatGPT account.', { remedy: 'Sign in again.' });
    }
    const catalog = await readModelCatalog({ request: (method, params) => server!.request(method, params, { signal: activeSignal }) }, undefined, false);
    const configuredModel = typeof server.effectiveConfig.model === 'string' ? server.effectiveConfig.model : undefined;
    const model = catalog.models.find(item => item.id === (parsed.model ?? configuredModel)) ??
      (request.model || configuredModel ? undefined : catalog.models.find(item => item.isDefault));
    if (!model) throw new Failure(request.model ? 'invalid_input' : 'tool_failed', request.model ? 'The requested model is not in the tool catalog.' : 'Codex did not identify its default model in the catalog.');
    const configuredEffort = typeof server.effectiveConfig.model_reasoning_effort === 'string' ? server.effectiveConfig.model_reasoning_effort : undefined;
    let effort = request.effort ?? configuredEffort ?? model.defaultEffort;
    if (request.effortFromSettings && request.effort && !model.efforts?.includes(request.effort)) {
      pendingNotices.push({ code: 'ignored_default_effort', message: 'The Subscription default effort is not supported by this model; the tool default is used.' });
      effort = configuredEffort ?? model.defaultEffort;
    }
    if (effort && !model.efforts?.includes(effort)) throw new Failure('invalid_input', 'The requested effort is not supported by the model.');
    if (request.serviceTier && !model.serviceTiers?.includes(request.serviceTier)) throw new Failure('invalid_input', 'The requested service tier is not supported by the model.');
    let thread: unknown;
    if (plan!.continuity === 'resumed') {
      try { thread = await server.request('thread/resume', { threadId: plan!.conversation, model: model.id }, { signal: activeSignal }); }
      catch (failure) {
        if (!(failure instanceof Failure) || failure.result.detail?.vendorCode === undefined || activeSignal.aborted) throw failure;
        plan = { ...plan!, continuity: 'rebuilt', rebuildReason: /no rollout found|thread not found|unknown thread|does not exist/i.test(failure.message) ? 'conversation_gone' : 'resume_refused' };
      }
    }
    if (plan!.continuity !== 'resumed') thread = await server.request('thread/start', { cwd, model: model.id, approvalPolicy: 'never',
      sandbox: request.tools === 'none' ? 'read-only' : 'danger-full-access',
      ...(request.serviceTier === undefined ? {} : { serviceTier: request.serviceTier }),
      ...(request.systemPrompt === undefined ? {} : { developerInstructions: request.systemPrompt }),
      ...(request.tools === 'none' && request.workingDirectory === undefined ? { ephemeral: true } : {}) }, { signal: activeSignal });
    if (!isObject(thread) || !isObject(thread.thread) || typeof thread.thread.id !== 'string' || typeof thread.model !== 'string') throw new Failure('tool_failed', 'Codex returned a malformed thread.');
    const restoredTurns = new Set(Array.isArray(thread.thread.turns) ? thread.thread.turns.flatMap(turn =>
      isObject(turn) && typeof turn.id === 'string' ? [turn.id] : []) : []);
    conversation = thread.thread.id;
    currentModel = thread.model;
    record.conversation = conversation; await runs.save(record);
    let turnInput: Pick<RunRequest['input'], 'text' | 'images'> = request.input;
    if (plan!.continuity === 'rebuilt' && request.history.length) {
      try { await server.request('thread/inject_items', { threadId: conversation, items: historyItems(request.history) }, { signal: activeSignal }); }
      catch (failure) {
        if (!(failure instanceof Failure) || failure.result.detail?.vendorCode === undefined || activeSignal.aborted) throw failure;
        turnInput = labelledHistoryInput(request.history, request.input);
        pendingNotices.push({ code: 'history_as_text', message: 'Codex refused the native history; the earlier conversation was sent as labelled text.' });
      }
    }
    const message = await prepareTurnInput(turnInput, temporary);
    // A resume restores the previous turn's usage and status. Only the new
    // turn's notifications count as events or token expenditure for this run.
    const startup = server.takeNotifications().filter(notification => ['warning', 'deprecationNotice'].includes(notification.method));
    const turn = await server.request('turn/start', { threadId: thread.thread.id, input: message, model: model.id, effort: effort ?? null,
      summary: 'detailed', approvalPolicy: 'never', sandboxPolicy: request.tools === 'none' ? { type: 'readOnly', networkAccess: false } : { type: 'dangerFullAccess' },
      ...(request.serviceTier === undefined ? {} : { serviceTier: request.serviceTier }) }, { signal: activeSignal });
    if (!isObject(turn) || !isObject(turn.turn) || typeof turn.turn.id !== 'string') throw new Failure('tool_failed', 'Codex returned a malformed turn.');
    mapper = new RunEvents(thread.thread.id, turn.turn.id, thread.model, (type, data) => {
      if (type === 'text' && data.parentCallId === undefined) fingerprint.add({ type: 'message', role: 'assistant', text: data.text as string });
      events.emit(type, data);
    });
    await writeJson(join(temporary, 'shell-owners.json'), await server.captureProcessGroups());
    events.emit('started', { continuity: plan!.continuity, ...(plan!.rebuildReason === undefined ? {} : { rebuildReason: plan!.rebuildReason }), subscriptionId: request.subscriptionId, model: thread.model,
      ...(effort === undefined ? {} : { effort }), toolVersion: server.toolVersion ?? tool.version!, driverBuild: build });
    started = true;
    for (const notification of startup) mapper.consume(notification.method, notification.params);
    for (const notice of pendingNotices) events.emit('notice', notice);
    for (const notice of subscriptions.notices) events.emit('notice', { ...notice });
    await events.flush(activeSignal);
    let remainingCallsDeadline: number | undefined;
    while (!mapper.outcome || mapper.openCalls.size || mapper.waitingForWork) {
      const waitingForOtherCalls = !!mapper.outcome && !mapper.waitingForWork;
      if (waitingForOtherCalls) remainingCallsDeadline ??= performance.now() + fixedWait(2000, env);
      const remaining = remainingCallsDeadline === undefined ? undefined : remainingCallsDeadline - performance.now();
      if (waitingForOtherCalls && remaining! <= 0) break;
      let notification;
      try { notification = await server.nextNotification({ signal: activeSignal, ...(waitingForOtherCalls ? { timeoutMs: remaining! } : {}) }); }
      catch (failure) { if (waitingForOtherCalls && failure instanceof Failure && /Timed out/.test(failure.message)) break; throw failure; }
      if (plan!.continuity === 'resumed' && notification.method === 'thread/tokenUsage/updated' &&
        isObject(notification.params) && notification.params.threadId === conversation &&
        (notification.params.turnId === undefined || typeof notification.params.turnId === 'string' && restoredTurns.has(notification.params.turnId))) continue;
      if (notification.method === 'item/started' && isObject(notification.params) &&
        isObject(notification.params.item) && notification.params.item.type === 'commandExecution') {
        // The vendor processId is a terminal identifier, never an OS PID.
        await writeJson(join(temporary, 'shell-owners.json'), await server.captureProcessGroups());
      }
      mapper.consume(notification.method, notification.params); await events.flush(activeSignal);
    }
    if (mapper.outcome === 'failed') error = new Failure(mapper.error?.code ?? 'vendor_error', mapper.error?.message ?? 'Codex failed the turn.', mapper.error ?? {});
    else if (mapper.outcome === 'interrupted') error = new Failure('tool_failed', 'Codex interrupted the turn without a caller stop.');
  } catch (failure) { error = failure; }
  finally {
    if (activeSignal.aborted && server) {
      if (!mapper && conversation) {
        const queued = server.takeNotifications();
        const announced = queued.find(notification => notification.method === 'turn/started' &&
          isObject(notification.params) && notification.params.threadId === conversation && isObject(notification.params.turn));
        if (announced && isObject(announced.params) && isObject(announced.params.turn) && typeof announced.params.turn.id === 'string') {
          mapper = new RunEvents(conversation, announced.params.turn.id, currentModel ?? '', (type, data) => events.emit(type, data));
          if (!started) events.emit('started', { continuity: plan!.continuity,
            ...(plan!.rebuildReason === undefined ? {} : { rebuildReason: plan!.rebuildReason }),
            subscriptionId: request!.subscriptionId, model: currentModel, toolVersion: server.toolVersion, driverBuild: build });
          for (const notification of queued) mapper.consume(notification.method, notification.params);
        }
      }
      if (mapper) await interruptTurns(server, mapper, stopAt! + fixedWait(2000, env)).catch(() => {});
    }
    // A caller may stop after the turn completed, while stdin EOF cleanup is
    // still waiting. Give that stop its own deadline and keep control readable.
    const stopDuringEnd = (): void => {
      void server?.close(stopAt! + fixedWait(15000, env), stopAt! + fixedWait(2000, env)).catch(() => {});
    };
    activeSignal.addEventListener('abort', stopDuringEnd, { once: true });
    try {
      await server?.end(stopAt === undefined ? undefined : stopAt + fixedWait(15000, env),
        stopAt === undefined ? undefined : stopAt + fixedWait(2000, env)).catch(failure => {
        error ??= failure;
        if (activeSignal.aborted) events.emit('notice', { code: 'cleanup_failed', message: failure.message });
      });
    } finally {
      activeSignal.removeEventListener('abort', stopDuringEnd);
      settled = true;
      input?.close();
      if (controlTask) await controlTask;
    }
    mapper?.closeOpenCalls(activeSignal.aborted ? 'The tool call was interrupted by the caller.' : undefined);
    if (temporary) await rm(temporary, { recursive: true, force: true }).catch(failure => { error ??= failure; });
  }
  if (request && plan && reservedId) {
    try { await events.flush(activeSignal); } catch (failure) { error ??= failure; }
    try {
      await chats.settle(request, plan, conversation, fingerprint.snapshot(), error === undefined && !activeSignal.aborted && mapper?.outcome === 'completed');
    } catch (failure) { error ??= failure; }
  }
  try {
    let outputTimer: ReturnType<typeof setTimeout> | undefined;
    let stopOutput!: () => void;
    const outputDeadline = new Promise<number>(resolve => {
      stopOutput = (): void => {
        if (outputTimer) return;
        outputTimer = setTimeout(() => { events.abandonOutput(); resolve(2); },
          Math.max(1, stopAt! + fixedWait(15000, env) - performance.now()));
      };
      activeSignal.addEventListener('abort', stopOutput, { once: true });
      if (activeSignal.aborted) stopOutput();
    });
    let code: number;
    try {
      code = await Promise.race([events.finish(error, activeSignal.aborted, { producedOutput: mapper?.outputProduced ?? false,
        unfinishedCalls: mapper?.unfinishedCalls ?? [], ...(mapper?.usage === undefined ? {} : { usage: mapper.usage }) }), outputDeadline]);
    } finally { clearTimeout(outputTimer); activeSignal.removeEventListener('abort', stopOutput); }
    if (code !== 0 && request && plan && reservedId && conversation) await chats.settle(request, { ...plan, continuedConversation: conversation }, conversation, fingerprint.snapshot(), false);
    return code;
  } catch (failure) {
    if (request && plan && reservedId && conversation) await chats.settle(request, { ...plan, continuedConversation: conversation }, conversation, fingerprint.snapshot(), false).catch(() => {});
    throw failure;
  } finally {
    events.output.off('error', outputClosed); activeSignal.removeEventListener('abort', markStop);
    if (reservedId) await runs.remove(reservedId);
  }
}
