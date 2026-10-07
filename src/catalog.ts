import { Failure } from './errors.js';
import { isObject } from './settings.js';

export interface Account { email?: string; plan?: string }
export interface UsageReport {
  outcome: 'ok' | 'needs_sign_in' | 'unavailable' | 'unsupported';
  message?: string;
  fetchedAt: string;
  plan?: string;
  windows: Array<{
    kind: 'session' | 'weekly' | 'other';
    label: string;
    usedPercent?: number;
    resetsAt?: string;
    windowMinutes?: number;
    limitReached?: boolean;
  }>;
  detailsUrl?: string;
  extra?: Record<string, unknown>;
}
export interface ModelCatalog {
  source: 'vendor' | 'tool' | 'builtin';
  fetchedAt: string;
  models: Array<{
    id: string;
    label: string;
    description?: string;
    efforts?: string[];
    serviceTiers?: string[];
    defaultEffort?: string;
    isDefault?: boolean;
  }>;
}
export interface RpcClient { request<T = unknown>(method: string, params: unknown): Promise<T> }

function malformed(name: string): never { throw new Failure('tool_failed', `codex returned a malformed ${name}.`); }
const nonempty = (value: unknown): value is string => typeof value === 'string' && value.trim().length > 0;

export function normalizeAccount(value: unknown): Account | undefined {
  if (!isObject(value) || !('account' in value)) malformed('account response');
  if (value.account === null) return undefined;
  const account = value.account;
  if (!isObject(account) || !nonempty(account.type)) malformed('account response');
  if (account.type !== 'chatgpt') return undefined;
  if (!nonempty(account.email) || !nonempty(account.planType)) malformed('ChatGPT account');
  return { email: account.email, plan: account.planType };
}

function windowLabel(minutes: number | undefined): string {
  if (minutes === 300) return '5-hour window';
  if (minutes === 10080) return 'Weekly window';
  if (minutes === undefined) return 'Usage window';
  const days = minutes / 1440;
  if (Number.isInteger(days)) return `${days}-day window`;
  return `${Number((minutes / 60).toFixed(2))}-hour window`;
}
function normalizeWindow(value: unknown): UsageReport['windows'][number] | undefined {
  if (value === null || value === undefined) return undefined;
  if (!isObject(value)) malformed('usage window');
  const minutes = value.windowDurationMins;
  if (minutes !== null && minutes !== undefined && (typeof minutes !== 'number' || !Number.isFinite(minutes) || minutes <= 0)) malformed('usage window');
  const duration = typeof minutes === 'number' ? minutes : undefined;
  const window: UsageReport['windows'][number] = {
    kind: duration === 300 ? 'session' : duration === 10080 ? 'weekly' : 'other',
    label: windowLabel(duration),
  };
  if (duration !== undefined) window.windowMinutes = duration;
  const percent = value.usedPercent;
  if (percent !== undefined && percent !== null) {
    if (typeof percent !== 'number' || !Number.isFinite(percent)) malformed('usage window');
    window.usedPercent = Math.max(0, Math.min(100, percent));
    window.limitReached = percent >= 100;
  }
  const reset = value.resetsAt;
  if (reset !== null && reset !== undefined) {
    if (typeof reset !== 'number' || !Number.isFinite(reset) || !Number.isFinite(new Date(reset * 1000).getTime())) malformed('usage reset time');
    window.resetsAt = new Date(reset * 1000).toISOString();
  }
  return window;
}

export function normalizeUsage(value: unknown, fallbackPlan?: string, fetchedAt = new Date().toISOString()): UsageReport {
  if (!isObject(value) || !('rateLimits' in value) && !isObject(value.rateLimitsByLimitId)) malformed('usage response');
  const byId = value.rateLimitsByLimitId;
  const limits = value.rateLimits ?? (isObject(byId) ? byId.codex ?? Object.values(byId)[0] : undefined);
  if (limits !== null && limits !== undefined && !isObject(limits)) malformed('usage response');
  const report: UsageReport = { outcome: 'ok', fetchedAt, windows: [], detailsUrl: 'https://chatgpt.com/codex/settings/usage' };
  const plan = isObject(limits) && nonempty(limits.planType) ? limits.planType : fallbackPlan;
  if (plan !== undefined) report.plan = plan;
  if (isObject(limits)) {
    for (const key of ['primary', 'secondary']) {
      const window = normalizeWindow(limits[key]);
      if (window) report.windows.push(window);
    }
  }
  const extra: Record<string, unknown> = {};
  for (const key of ['ordinaryUsageAllowed', 'rateLimitsByLimitId', 'rateLimitResetCredits', 'rateLimitUpsell']) {
    if (key in value) extra[key] = value[key];
  }
  if (isObject(limits)) {
    for (const key of ['rateLimitReachedType', 'credits', 'spendControlReached', 'individualLimit']) {
      if (key in limits) extra[key] = limits[key];
    }
  }
  if (Object.keys(extra).length) report.extra = extra;
  return report;
}

export function normalizeModels(value: unknown, source: ModelCatalog['source'] = 'tool', fetchedAt = new Date().toISOString()): ModelCatalog {
  if (!Array.isArray(value)) malformed('model list');
  const models: ModelCatalog['models'] = [];
  const seen = new Set<string>();
  for (const raw of value) {
    if (!isObject(raw)) malformed('model');
    if (raw.hidden === true) continue;
    if (!nonempty(raw.id) || !nonempty(raw.displayName)) malformed('model');
    if (seen.has(raw.id)) continue;
    seen.add(raw.id);
    const model: ModelCatalog['models'][number] = { id: raw.id, label: raw.displayName };
    if (raw.description !== undefined && raw.description !== null) {
      if (typeof raw.description !== 'string') malformed('model description');
      model.description = raw.description;
    }
    if (raw.supportedReasoningEfforts !== undefined) {
      if (!Array.isArray(raw.supportedReasoningEfforts)) malformed('model efforts');
      model.efforts = [...new Set(raw.supportedReasoningEfforts.map((effort: unknown) => {
        if (!isObject(effort) || !nonempty(effort.reasoningEffort)) malformed('model effort');
        return effort.reasoningEffort;
      }))];
    }
    if (raw.defaultReasoningEffort !== undefined && raw.defaultReasoningEffort !== null) {
      if (!nonempty(raw.defaultReasoningEffort)) malformed('default model effort');
      model.defaultEffort = raw.defaultReasoningEffort;
    }
    if (raw.serviceTiers !== undefined) {
      if (!Array.isArray(raw.serviceTiers)) malformed('model service tiers');
      model.serviceTiers = [...new Set(raw.serviceTiers.map((tier: unknown) => {
        if (!isObject(tier) || !nonempty(tier.id)) malformed('model service tier');
        return tier.id;
      }))];
    }
    if (raw.isDefault !== undefined) {
      if (typeof raw.isDefault !== 'boolean') malformed('default model flag');
      model.isDefault = raw.isDefault;
    }
    models.push(model);
  }
  return { source, fetchedAt, models };
}

// Captured from model/list in codex-cli 0.159.2 on 6 October 2026. This
// intentionally stays at the last verified list when the tool cannot answer.
const fullEfforts = ['low', 'medium', 'high', 'xhigh', 'max', 'ultra'];
const builtinModels = [
  ['gpt-6.1-sol', 'GPT-6.1-Sol', 'Latest workhorse model for coding and everyday work.', 'low', true, fullEfforts],
  ['gpt-6-astra', 'GPT-6-Astra', 'Frontier intelligence for the most demanding work.', 'medium', false, fullEfforts],
  ['gpt-6-sol', 'GPT-6-Sol', 'Previous generation workhorse model.', 'medium', false, fullEfforts],
  ['gpt-6-luna', 'GPT-6-Luna', 'Fast and affordable model for easier tasks.', 'medium', false, fullEfforts.slice(0, -1)],
  ['gpt-5.6-sol', 'GPT-5.6-Sol', 'Older generation workhorse model.', 'low', false, fullEfforts],
  ['gpt-5.6-terra', 'GPT-5.6-Terra', 'Older balanced model for straightforward work.', 'medium', false, fullEfforts],
  ['gpt-5.6-luna', 'GPT-5.6-Luna', 'Older fast and efficient model.', 'medium', false, fullEfforts.slice(0, -1)],
] as const;
export function builtinCatalog(fetchedAt = new Date().toISOString()): ModelCatalog {
  return { source: 'builtin', fetchedAt, models: builtinModels.map(([id, label, description, defaultEffort, isDefault, efforts]) =>
    ({ id, label, description, defaultEffort, isDefault, efforts: [...efforts], serviceTiers: ['priority'] })) };
}
export const builtinModelCatalog = builtinCatalog;

export async function readModelCatalog(server: RpcClient, fetchedAt = new Date().toISOString()): Promise<ModelCatalog> {
  try {
    const raw: unknown[] = [];
    const seen = new Set<string>();
    let cursor: string | undefined;
    do {
      const page = await server.request('model/list', cursor === undefined ? { includeHidden: false } : { includeHidden: false, cursor });
      if (!isObject(page) || !Array.isArray(page.data)) malformed('model list page');
      raw.push(...page.data);
      if (page.nextCursor === undefined || page.nextCursor === null) cursor = undefined;
      else {
        if (!nonempty(page.nextCursor) || seen.has(page.nextCursor)) malformed('model list cursor');
        cursor = page.nextCursor;
        seen.add(cursor);
      }
    } while (cursor !== undefined);
    return normalizeModels(raw, 'tool', fetchedAt);
  } catch (error) {
    if (error instanceof Failure && error.result.code === 'credential_rejected') throw error;
    return builtinCatalog(fetchedAt);
  }
}
