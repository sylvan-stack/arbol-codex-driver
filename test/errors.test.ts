import { test } from 'node:test';
import assert from 'node:assert/strict';
import { DriverFailure, Failure, errorCodes, errno, raise, redact, safeError, safeFailure, safeText } from '../src/errors.js';

test('errors uses the closed contract classifications and exact retry policy', () => {
  assert.deepEqual(errorCodes, ['invalid_input', 'not_found', 'in_use', 'unsupported', 'not_signed_in', 'credential_rejected',
    'rate_limited', 'context_exceeded', 'vendor_unavailable', 'vendor_error', 'tool_missing', 'tool_unsupported', 'tool_failed',
    'limit_reached', 'state_newer', 'internal']);
  for (const code of errorCodes) {
    const result = new Failure(code, 'Failure.').result;
    assert.equal(result.code, code);
    assert.equal(result.message, 'Failure.');
    assert.equal(result.retryable, code === 'rate_limited' || code === 'vendor_unavailable');
  }
  assert.throws(() => new Failure('unknown' as never, 'Failure.'), /Unknown Driver error code/);
});

test('errors retains typed failures and hides every unexpected exception', () => {
  const failure = new Failure('not_found', 'The run does not exist.');
  assert.equal(safeFailure(failure), failure.result);
  assert.equal(safeError(failure), failure.result);
  assert.equal(DriverFailure, Failure);
  for (const unexpected of [new Error('synthetic-secret-sentinel'), 'synthetic-secret-sentinel', { error: 'synthetic-secret-sentinel' }, null]) {
    assert.deepEqual(safeFailure(unexpected), { code: 'internal', message: 'The Driver could not complete this operation.', retryable: false });
  }
  assert.throws(() => raise('invalid_input', 'Change the request.'), (error: unknown) => error instanceof Failure && error.result.code === 'invalid_input');
  assert.equal(errno(Object.assign(new Error('Missing'), { code: 'ENOENT' }), 'ENOENT'), true);
  assert.equal(errno(Object.assign(new Error('Denied'), { code: 'EACCES' }), 'ENOENT'), false);
  assert.equal(errno({ code: 'ENOENT' }, 'ENOENT'), false);
});

test('errors retains classification evidence and only attaches vendor waits to rate limits', () => {
  const detail = { basis: 'fields' as const, vendorStatus: 429, vendorCode: 'rate_limit', toolVersion: '0.140.0', neededVersion: '0.140.0' };
  assert.deepEqual(new Failure('rate_limited', 'Account limit.', { detail, retryAfterSeconds: 300 }).result,
    { code: 'rate_limited', message: 'Account limit.', retryable: true, retryAfterSeconds: 300, detail });
  assert.equal(new Failure('rate_limited', 'Account limit.').result.retryAfterSeconds, undefined);
  for (const code of errorCodes.filter(code => code !== 'rate_limited')) {
    assert.equal(new Failure(code, 'Failure.', { retryAfterSeconds: 300 }).result.retryAfterSeconds, undefined);
  }
  assert.deepEqual(new Failure('vendor_error', 'Vendor refused.', { detail: { basis: 'wording' } }).result.detail, { basis: 'wording' });
});

test('errors redacts known credentials from message, remedy and diagnostic fields before truncation', () => {
  const secret = 'synthetic-secret-sentinel';
  const failure = new Failure('tool_failed', `The tool said ${secret}.`, {
    remedy: `Replace ${secret}.`, detail: { basis: 'fields', vendorCode: secret, excerpt: 'old start ' + '😀'.repeat(600) + secret + ' tail', toolExit: 1 },
  }, [secret]);
  assert.equal(failure.message, 'The tool said [redacted].');
  assert.equal(failure.result.remedy, 'Replace [redacted].');
  assert.equal(failure.result.detail!.vendorCode, '[redacted]');
  assert.equal(JSON.stringify(failure.result).includes(secret), false);
  assert.ok(Buffer.byteLength(failure.result.detail!.excerpt!, 'utf8') <= 1024);
  assert.ok(failure.result.detail!.excerpt!.endsWith('[redacted] tail'));
  assert.equal(failure.result.detail!.excerpt!.includes('old start'), false);
  assert.equal(failure.result.detail!.excerpt!.includes('�'), false);
});

test('errors preserves Unicode and takes at most one KiB from the end of tool output', () => {
  for (const text of ['a'.repeat(1500), 'é'.repeat(600), '🦊'.repeat(400), 'a' + '🦊'.repeat(400)]) {
    const bounded = safeText(text);
    assert.ok(Buffer.byteLength(bounded, 'utf8') <= 1024);
    assert.ok(text.endsWith(bounded));
    assert.equal(bounded.includes('�'), false);
  }
  assert.equal(safeText('unchanged'), 'unchanged');
  assert.equal(safeText('abcdef', [], 3), 'def');
  assert.equal(safeText('prefixlongsecret suffix', ['long', 'longsecret']), 'prefix[redacted] suffix');
  assert.equal(safeText('secret', ['']), 'secret');
  assert.deepEqual(redact({ 'secret-key': ['secret-value', 4, null], nested: { text: 'secret-value' } }, ['secret']),
    { '[redacted]-key': ['[redacted]-value', 4, null], nested: { text: '[redacted]-value' } });
});
