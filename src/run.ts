import { createInterface } from 'node:readline';
import { realpath, rm, writeFile } from 'node:fs/promises';
import { delimiter, join } from 'node:path';
import { AppServer } from './app-server.js';
import { normalizeAccount, readModelCatalog } from './catalog.js';
import { Failure } from './errors.js';
import { EventStream } from './event-stream.js';
import { RunEvents } from './run-events.js';
import { readRunRequest } from './run-request.js';
import { Runs } from './runs.js';
import { isObject } from './settings.js';
import { fixedWait, privateDirectory, readJson } from './state.js';
import { inspectTool, requireTool } from './tool.js';
import type { Command } from './arguments.js';
import type { Subscriptions } from './subscriptions.js';
import type { ProcessEnv } from './types.js';

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
  const pendingNotices: Array<Record<string, unknown>> = [];
  const localStop = new AbortController();
  const activeSignal = AbortSignal.any([signal, localStop.signal]);
  const outputClosed = (): void => localStop.abort();
  events.output.on('error', outputClosed);
  const runs = new Runs(subscriptions.state);
  try {
    const request = await readRunRequest(command.options, { settings: subscriptions.settings,
      ...(command.positionals[0] === undefined ? {} : { message: command.positionals[0] }),
      firstLine: async () => {
        const line = await lines!.next();
        if (line.done) throw new Failure('invalid_input', 'The request line is missing.'); return line.value;
      }, identity: (runId, labels) => { events.runId = runId; events.labels = labels; } });
    events.textOnly = request.output === 'text';
    if (!request.control) input?.close();
    if (request.history.length) throw new Failure('unsupported', 'Continuing a conversation is not implemented yet (SYL-88).');
    const subscription = await subscriptions.requireSignedIn(request.subscriptionId);
    await runs.list(); await subscriptions.state.clearUnfinishedWrites();
    const record = await subscriptions.state.withSubscriptionLock(subscription.id, async () => {
      const current = await subscriptions.record(subscription.id);
      if (current.state !== 'signed_in') throw new Failure('not_signed_in', 'Sign in to this Subscription first.');
      if (await readJson(join(subscriptions.state.subscription(subscription.id), 'sign-in.json')) !== undefined) throw new Failure('in_use', 'An account operation is still in progress.');
      return runs.reserve({ runId: request.runId, subscriptionId: request.subscriptionId,
        ...(request.labels === undefined ? {} : { labels: request.labels }),
        ...(request.chatSessionId === undefined ? {} : { chatSessionId: request.chatSessionId }) });
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
        await events.flush();
      }
      if (!settled) localStop.abort();
    })().catch(() => { if (!settled) localStop.abort(); });
    const tool = await inspectTool(subscriptions.state, subscriptions.settings.toolPath, env, activeSignal); requireTool(tool);
    server = await AppServer.start({ toolPath: tool.path!, home: join(subscriptions.state.subscription(subscription.id), 'home'),
      cwd, env: childEnv, signal: activeSignal, requestTimeoutMs: fixedWait(30000, env),
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
    const model = catalog.models.find(item => item.id === (request.model ?? configuredModel)) ??
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
    const thread = await server.request('thread/start', { cwd, model: model.id, approvalPolicy: 'never',
      sandbox: request.tools === 'none' ? 'read-only' : 'danger-full-access',
      ...(request.serviceTier === undefined ? {} : { serviceTier: request.serviceTier }),
      ...(request.systemPrompt === undefined ? {} : { developerInstructions: request.systemPrompt }),
      ...(request.tools === 'none' && request.workingDirectory === undefined ? { ephemeral: true } : {}) }, { signal: activeSignal });
    if (!isObject(thread) || !isObject(thread.thread) || typeof thread.thread.id !== 'string' || typeof thread.model !== 'string') throw new Failure('tool_failed', 'Codex returned a malformed thread.');
    record.conversation = thread.thread.id; await runs.save(record);
    const message: Record<string, unknown>[] = [{ type: 'text', text: request.input.text }];
    const extension = { 'image/png': 'png', 'image/jpeg': 'jpg', 'image/webp': 'webp', 'image/gif': 'gif' };
    for (const [index, picture] of (request.input.images ?? []).entries()) {
      const path = join(temporary, `image-${index}.${extension[picture.mediaType]}`);
      await writeFile(path, Buffer.from(picture.data, 'base64'), { mode: 0o600 }); message.push({ type: 'localImage', path });
    }
    const turn = await server.request('turn/start', { threadId: thread.thread.id, input: message, model: model.id, effort: effort ?? null,
      summary: 'detailed', approvalPolicy: 'never', sandboxPolicy: request.tools === 'none' ? { type: 'readOnly', networkAccess: false } : { type: 'dangerFullAccess' },
      ...(request.serviceTier === undefined ? {} : { serviceTier: request.serviceTier }) }, { signal: activeSignal });
    if (!isObject(turn) || !isObject(turn.turn) || typeof turn.turn.id !== 'string') throw new Failure('tool_failed', 'Codex returned a malformed turn.');
    mapper = new RunEvents(thread.thread.id, turn.turn.id, thread.model, (type, data) => events.emit(type, data));
    events.emit('started', { continuity: 'fresh', subscriptionId: request.subscriptionId, model: thread.model,
      ...(effort === undefined ? {} : { effort }), toolVersion: server.toolVersion ?? tool.version!, driverBuild: build });
    started = true;
    for (const notice of pendingNotices) events.emit('notice', notice);
    for (const notice of subscriptions.notices) events.emit('notice', { ...notice });
    await events.flush();
    let remainingCallsDeadline: number | undefined;
    while (!mapper.outcome || mapper.openCalls.size) {
      const waitingForOtherCalls = !!mapper.outcome && ![...mapper.openCalls.values()].some(call => call.type === 'commandExecution');
      if (waitingForOtherCalls) remainingCallsDeadline ??= performance.now() + fixedWait(2000, env);
      const remaining = remainingCallsDeadline === undefined ? undefined : remainingCallsDeadline - performance.now();
      if (waitingForOtherCalls && remaining! <= 0) break;
      let notification;
      try { notification = await server.nextNotification({ signal: activeSignal, ...(waitingForOtherCalls ? { timeoutMs: remaining! } : {}) }); }
      catch (failure) { if (waitingForOtherCalls && failure instanceof Failure && /Timed out/.test(failure.message)) break; throw failure; }
      mapper.consume(notification.method, notification.params); await events.flush();
    }
    if (mapper.outcome === 'failed') error = new Failure(mapper.error?.code ?? 'vendor_error', mapper.error?.message ?? 'Codex failed the turn.', mapper.error ?? {});
    else if (mapper.outcome === 'interrupted') error = new Failure('tool_failed', 'Codex interrupted the turn without a caller stop.');
    settled = true;
  } catch (failure) { error = failure; }
  finally {
    settled = true; input?.close();
    if (controlTask) await controlTask;
    await server?.end().catch(failure => { error ??= failure; });
    mapper?.closeOpenCalls();
    if (temporary) await rm(temporary, { recursive: true, force: true }).catch(failure => { error ??= failure; });
    events.output.off('error', outputClosed);
  }
  try {
    return await events.finish(error, activeSignal.aborted, { producedOutput: mapper?.outputProduced ?? false,
      unfinishedCalls: mapper?.unfinishedCalls ?? [], ...(mapper?.usage === undefined ? {} : { usage: mapper.usage }) });
  } finally { if (reservedId) await runs.remove(reservedId); }
}
