import assert from 'node:assert/strict';
import { test } from 'node:test';
import { builtinCatalog, normalizeAccount, normalizeModels, normalizeUsage, readModelCatalog } from '../src/catalog.js';
import { Failure } from '../src/errors.js';
const now = '2026-10-07T12:00:00.000Z';
const model = (id: string, extra: Record<string, unknown> = {}) => ({
  id, displayName: `Label ${id}`, description: 'Description', hidden: false,
  supportedReasoningEfforts: [{ reasoningEffort: 'low' }, { reasoningEffort: 'future_effort' }],
  defaultReasoningEffort: 'future_effort', isDefault: false, serviceTiers: [{ id: 'priority' }, { id: 'future_tier' }], ...extra,
});

test('catalog.account accepts ChatGPT and treats absent or other account kinds as unavailable', () => {
  assert.deepEqual(normalizeAccount({ account: { type: 'chatgpt', email: 'user@example.com', planType: 'future_plan', secret: 'unused' } }), { email: 'user@example.com', plan: 'future_plan' });
  assert.equal(normalizeAccount({ account: null }), undefined);
  assert.equal(normalizeAccount({ account: { type: 'apiKey' } }), undefined);
  for (const value of [null, {}, { account: [] }, { account: { type: 'chatgpt' } }]) assert.throws(() => normalizeAccount(value), Failure);
});

test('catalog.usage recognizes windows by length, maps resets, and preserves credit and limit details', () => {
  const limits = {
    primary: { usedPercent: 100, windowDurationMins: 10080, resetsAt: 1791388800 },
    secondary: { usedPercent: 12.5, windowDurationMins: 300, resetsAt: null },
    planType: 'pro', credits: { balance: '12.50', hasCredits: true, unlimited: false }, rateLimitReachedType: 'weekly',
  };
  const usage = normalizeUsage({ ordinaryUsageAllowed: true, rateLimits: limits, rateLimitsByLimitId: { codex: limits } }, 'plus', now);
  assert.deepEqual(usage.windows, [
    { kind: 'weekly', label: 'Weekly window', usedPercent: 100, windowMinutes: 10080, limitReached: true, resetsAt: '2026-10-07T16:00:00.000Z' },
    { kind: 'session', label: '5-hour window', usedPercent: 12.5, windowMinutes: 300, limitReached: false },
  ]);
  assert.equal(usage.plan, 'pro');
  assert.equal(usage.fetchedAt, now);
  assert.equal(usage.detailsUrl, 'https://chatgpt.com/codex/settings/usage');
  assert.deepEqual(usage.extra, { ordinaryUsageAllowed: true, rateLimitsByLimitId: { codex: limits }, credits: limits.credits, rateLimitReachedType: 'weekly' });
});

test('catalog.unknowns handles unknown and absent windows without assigning unavailable values as zero', () => {
  const usage = normalizeUsage({ rateLimits: { primary: { windowDurationMins: 1440, usedPercent: 110 }, secondary: { usedPercent: null }, planType: null } }, 'plus', now);
  assert.deepEqual(usage.windows, [
    { kind: 'other', label: '1-day window', usedPercent: 100, windowMinutes: 1440, limitReached: true },
    { kind: 'other', label: 'Usage window' },
  ]);
  assert.equal(usage.plan, 'plus');
  assert.equal(normalizeUsage({ rateLimits: null }, undefined, now).windows.length, 0);
  assert.equal(normalizeUsage({ rateLimitsByLimitId: { codex: { primary: { usedPercent: 1, windowDurationMins: 600 } } } }).windows[0]!.label, '10-hour window');
});

test('catalog.malformed rejects malformed usage fields cleanly', () => {
  for (const value of [null, {}, { rateLimits: [] }, { rateLimits: { primary: [] } },
    { rateLimits: { primary: { usedPercent: '100' } } }, { rateLimits: { primary: { usedPercent: NaN } } },
    { rateLimits: { primary: { windowDurationMins: -1 } } }, { rateLimits: { primary: { resetsAt: Infinity } } }]) {
    assert.throws(() => normalizeUsage(value), Failure);
  }
});

test('catalog.models retains unknown effort and service-tier identifiers, skips hidden entries, and deduplicates', () => {
  assert.deepEqual(normalizeModels([model('one'), model('hidden', { hidden: true }), model('one')], 'tool', now), {
    source: 'tool', fetchedAt: now,
    models: [{ id: 'one', label: 'Label one', description: 'Description', efforts: ['low', 'future_effort'],
      defaultEffort: 'future_effort', isDefault: false, serviceTiers: ['priority', 'future_tier'] }],
  });
  for (const value of [null, [{}], [model('a', { supportedReasoningEfforts: [null] })], [model('a', { serviceTiers: [{}] })]]) {
    assert.throws(() => normalizeModels(value), Failure);
  }
});

test('catalog.pages follows all pages and explicitly leaves hidden models out', async () => {
  const requests: unknown[] = [];
  const server = { async request<T>(method: string, params: unknown): Promise<T> {
    requests.push({ method, params });
    return (requests.length === 1 ? { data: [model('one')], nextCursor: 'second' } : { data: [model('two')], nextCursor: null }) as T;
  } };
  const catalog = await readModelCatalog(server, now);
  assert.equal(catalog.source, 'tool');
  assert.deepEqual(catalog.models.map(item => item.id), ['one', 'two']);
  assert.deepEqual(requests, [{ method: 'model/list', params: { includeHidden: false } }, { method: 'model/list', params: { includeHidden: false, cursor: 'second' } }]);
});

test('catalog.fallback handles errors and malformed or cyclic pages and propagates explicit credential rejection', async () => {
  for (const page of [null, {}, { data: [{}] }, { data: [model('one')], nextCursor: 'same' }]) {
    const server = { async request<T>(): Promise<T> { return page as T; } };
    assert.deepEqual(await readModelCatalog(server, now), builtinCatalog(now));
  }
  const unavailable = { async request<T>(): Promise<T> { throw new Failure('tool_failed', 'Unavailable'); } };
  assert.equal((await readModelCatalog(unavailable)).source, 'builtin');
  const rejected = { async request<T>(): Promise<T> { throw new Failure('credential_rejected', 'Expired'); } };
  await assert.rejects(readModelCatalog(rejected), error => error instanceof Failure && error.result.code === 'credential_rejected');
  const builtin = builtinCatalog();
  builtin.models[0]!.efforts!.push('mutation');
  assert.equal(builtinCatalog().models[0]!.efforts!.includes('mutation'), false);
});
