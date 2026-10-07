import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseArguments } from '../src/arguments.js';
import { Failure } from '../src/errors.js';

test('arguments accepts the contract command frame and states which commands need the tool', () => {
  const commands: [string[], string, boolean][] = [
    [['info'], 'info', false],
    [['run', 'hello'], 'run', true],
    [['runs', 'list'], 'runs list', false],
    [['runs', 'stop', 'run-1'], 'runs stop', false],
    [['subscriptions', 'families'], 'subscriptions families', false],
    [['subscriptions', 'list'], 'subscriptions list', false],
    [['subscriptions', 'create', '--family', 'chatgpt', '--label', 'Work'], 'subscriptions create', false],
    [['subscriptions', 'update', 'work', '--label', 'Updated'], 'subscriptions update', false],
    [['subscriptions', 'remove', 'work', '--force'], 'subscriptions remove', false],
    [['subscriptions', 'sign-in', 'work', '--by-code'], 'subscriptions sign-in', true],
    [['subscriptions', 'sign-out', 'work', '--force'], 'subscriptions sign-out', false],
    [['subscriptions', 'check', 'work'], 'subscriptions check', true],
    [['subscriptions', 'usage', 'work'], 'subscriptions usage', false],
    [['subscriptions', 'models', 'work'], 'subscriptions models', true],
    [['subscriptions', 'import', 'work', '--from', '/import'], 'subscriptions import', false],
    [['dev', 'probe'], 'dev probe', true],
    [['dev', 'live-check'], 'dev live-check', true],
    [['dev', 'build-check'], 'dev build-check', true],
  ];
  for (const [args, name, toolRequired] of commands) {
    const parsed = parseArguments(args);
    assert.equal(parsed.name, name, args.join(' '));
    assert.equal(parsed.toolRequired, toolRequired, name);
  }
});

test('arguments accepts separated and equals values, repeated values and a global state directory', () => {
  const parsed = parseArguments(['--state-dir', '/state', 'run', '--subscription=work', '--model', 'gpt-5.4', '--effort=high',
    '--service-tier', 'fast', '--add-dir', '/one', '--add-dir=/two', '--label=first', '--label', 'second', '--control', 'hello']);
  assert.deepEqual(parsed.options, { 'state-dir': '/state', subscription: 'work', model: 'gpt-5.4', effort: 'high',
    'service-tier': 'fast', 'add-dir': ['/one', '/two'], label: ['first', 'second'], control: true });
  assert.deepEqual(parsed.positionals, ['hello']);
  assert.equal(parseArguments(['subscriptions', '--state-dir=/state', 'list']).options['state-dir'], '/state');
  assert.equal(parseArguments(['info', '--state-dir=/state']).options['state-dir'], '/state');
  assert.deepEqual(parseArguments(['run', '--request=/request.json', '--output=text', '--tools=none']).positionals, []);
});

test('arguments preserves positional values and stand-in arguments after the separator', () => {
  assert.deepEqual(parseArguments(['run', '--', '--state-dir']).positionals, ['--state-dir']);
  const parsed = parseArguments(['dev', 'stand-in', '/folder', '--', '--state-dir', '/vendor']);
  assert.deepEqual(parsed, { name: 'dev stand-in', positionals: ['/folder', '--', '--state-dir', '/vendor'], options: {}, toolRequired: false });
});

test('arguments rejects malformed input without repeating its contents', () => {
  const sentinel = 'synthetic-secret-sentinel';
  const invalid = [[], [sentinel], ['subscriptions'], ['runs', 'stop'], ['info', sentinel], ['info', '--secret', sentinel],
    ['info', '--state-dir'], ['info', '--state-dir='], ['info', '--state-dir', '--another'],
    ['--state-dir=/one', 'info', '--state-dir=/two'], ['info', '-v', 'a3'], ['run', '--model'],
    ['run', '--model='], ['run', '--model', '--control'], ['run', '--model=one', '--model=two'],
    ['run', '--control=yes'], ['run', '--control', '--control'], ['run', '--tools=some'], ['run', '--output=unknown'],
    ['run', 'one', 'two'], ['dev', 'stand-in', '/folder'], ['dev', 'stand-in', '/folder', 'extra', '--', '--version']];
  for (const args of invalid) {
    assert.throws(() => parseArguments(args), (error: unknown) => {
      assert.ok(error instanceof Failure, args.join(' '));
      assert.equal(error.result.code, 'invalid_input');
      assert.equal(error.result.retryable, false);
      assert.equal(JSON.stringify(error.result).includes(sentinel), false);
      return true;
    });
  }
});
