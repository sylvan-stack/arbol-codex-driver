import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawn, execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { mkdir, readFile, stat, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { processOwner, writeJson } from '../src/state.js';
import { cli, fixture, invoke } from './helpers.js';

const exec = promisify(execFile);

// Inference is implemented separately. These are contract-shaped RunRecords
// with a synthetic owner that acknowledges SIGTERM and exits, plus a separate
// tool process group. They prove subscription refusal, cancellation and stale
// scratch/tool cleanup without claiming that a real Driver run was exercised.
for (const operation of ['sign-out', 'remove'] as const) {
  test(`subscriptions.active-run ${operation} refuses an active account and --force cancels before clearing it`, { timeout: 10000 }, async t => {
    const f = await fixture(t);
    await writeFile(join(f.tool, 'scenario'), 'C5 success\n');
    const created = await invoke(['subscriptions', 'create', '--family', 'chatgpt', '--label', 'Work', '--id', 'work', '--state-dir', f.state], f.env);
    assert.equal(created.code, 0);
    const account = join(f.state, 'subscriptions', 'work', 'record.json');
    await writeJson(account, { ...created.result, settings: undefined, state: 'signed_in', account: { email: 'fixture@example.invalid' },
      checkedAt: '2026-10-06T00:00:00Z', lastUsage: { outcome: 'ok', fetchedAt: '2026-10-06T00:00:00Z', windows: [] } });
    await writeFile(join(f.state, 'subscriptions', 'work', 'home', 'auth.json'), '{"credential":"fixture-vendor-secret"}', { mode: 0o600 });
    const cancelled = join(f.home, 'cancellation-acknowledged');
    const owner = spawn(process.execPath, ['-e', `
      const fs = require('node:fs');
      process.on('SIGTERM', () => { fs.writeFileSync(process.argv[1], 'cancelled'); process.exit(0); });
      console.log('ready'); setInterval(() => {}, 1000);
    `, cancelled], { stdio: ['ignore', 'pipe', 'ignore'] });
    const ownerDone = new Promise<number | null>(resolve => owner.once('close', code => resolve(code)));
    const tool = spawn('/bin/sleep', ['60'], { detached: true, stdio: 'ignore' });
    const toolDone = new Promise<void>(resolve => tool.once('close', () => resolve()));
    t.after(() => {
      if (owner.exitCode === null && owner.signalCode === null) owner.kill('SIGKILL');
      if (tool.pid) try { process.kill(-tool.pid, 'SIGKILL'); } catch { /* Already stopped. */ }
    });
    await new Promise<void>((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('Synthetic run owner did not become ready.')), 3000);
      owner.stdout!.once('data', () => { clearTimeout(timer); resolve(); });
      owner.once('error', error => { clearTimeout(timer); reject(error); });
    });
    assert.ok(owner.pid); assert.ok(tool.pid);
    const runOwner = await processOwner(owner.pid), toolOwner = await processOwner(tool.pid);
    assert.ok(runOwner); assert.ok(toolOwner);
    const run = join(f.state, 'runs', 'active.json'), scratch = join(f.state, 'tmp', 'active');
    await mkdir(scratch, { recursive: true }); await writeFile(join(scratch, 'work'), 'temporary run data');
    await writeJson(run, { runId: 'active', subscriptionId: 'work', owner: runOwner, tool: toolOwner, startedAt: new Date().toISOString() });
    const original = await readFile(account, 'utf8');
    const refused = await invoke(['subscriptions', operation, 'work', '--state-dir', f.state], f.env);
    assert.equal(refused.code, 1); assert.equal(refused.result.error.code, 'in_use');
    assert.equal(await readFile(account, 'utf8'), original);
    await assert.rejects(stat(join(f.tool, 'received.jsonl')), { code: 'ENOENT' });
    assert.ok(await processOwner(owner.pid));
    const forced = await exec(process.execPath, [cli, 'subscriptions', operation, 'work', '--force', '--state-dir', f.state], { env: f.env, timeout: 10000 });
    assert.equal(await ownerDone, 0); await toolDone;
    assert.equal(await readFile(cancelled, 'utf8'), 'cancelled');
    assert.equal(await processOwner(owner.pid), undefined); assert.equal(await processOwner(tool.pid), undefined);
    await assert.rejects(stat(run), { code: 'ENOENT' }); await assert.rejects(stat(scratch), { code: 'ENOENT' });
    if (operation === 'sign-out') {
      const signedOut = JSON.parse(forced.stdout);
      assert.equal(signedOut.state, 'signed_out');
      for (const field of ['account', 'problem', 'lastUsage']) assert.equal(signedOut[field], undefined);
      await assert.rejects(stat(join(f.state, 'subscriptions', 'work', 'home', 'auth.json')), { code: 'ENOENT' });
    } else {
      assert.equal(forced.stdout, ''); await assert.rejects(stat(account), { code: 'ENOENT' });
      await assert.rejects(stat(join(f.state, 'subscriptions', 'work', 'home')), { code: 'ENOENT' });
    }
  });
}
