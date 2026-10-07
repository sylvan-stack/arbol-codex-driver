import assert from 'node:assert/strict';
import { test } from 'node:test';
import { execFile, spawn } from 'node:child_process';
import { promisify } from 'node:util';
import { readFile, stat, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { cli, fixture } from './helpers.js';
import { ownerAlive } from '../src/state.js';
const exec = promisify(execFile);

test('stop.backpressure cleans the tool before an unread event pipe exhausts the cancellation deadline', async t => {
  for (const stop of ['SIGTERM', 'control'] as const) await t.test(stop, async t => {
    const f = await fixture(t); f.env.ARBOL_TEST_TIME_SCALE = '10';
    await writeFile(join(f.tool, 'scenario'), 'C10 success');
    await exec(process.execPath, [cli, 'subscriptions', 'sign-in', 'chatgpt', '--state-dir', f.state], { env: f.env, timeout: 10000 });
    await writeFile(join(f.tool, 'scenario'), 'C20 structure'); await writeFile(join(f.tool, 'received.jsonl'), '');
    const child = spawn(process.execPath, [cli, 'run', '--run-id', 'backpressure', '--subscription', 'chatgpt',
      '--state-dir', f.state, '--tools', 'all', '--cwd', f.home, ...(stop === 'control' ? ['--control'] : []), 'answer'], { env: f.env, stdio: 'pipe' });
    // Keep stdout open while withholding reads: the >200 KiB result fills its pipe.
    child.stdout.pause(); child.stdin.on('error', () => {}); child.stderr.resume();
    const safety = setTimeout(() => child.kill('SIGKILL'), 10000);
    t.after(() => { clearTimeout(safety); if (child.exitCode === null && child.signalCode === null) child.kill('SIGKILL'); child.stdout.destroy(); child.stdin.destroy(); });
    const exited = new Promise<{ code: number | null; signal: NodeJS.Signals | null }>(resolve => child.once('exit', (code, signal) => resolve({ code, signal })));
    const deadline = performance.now() + 5000;
    while (child.stdout.readableLength < 32768) {
      assert.equal(child.exitCode, null, 'The Driver must be blocked on the unconsumed result.');
      assert.ok(performance.now() < deadline, 'The fixture must fill the event pipe.');
      await new Promise(resolve => setTimeout(resolve, 10));
    }
    await new Promise(resolve => setTimeout(resolve, 100));
    const record = JSON.parse(await readFile(join(f.state, 'runs', 'backpressure.json'), 'utf8'));
    assert.equal(await ownerAlive(record.tool), true); assert.equal(child.exitCode, null);
    const start = performance.now();
    // A refusal queues behind the blocked tool result. Its output must not keep
    // the control reader from acting on the following stop line.
    if (stop === 'control') child.stdin.write('{"type":"invalid"}\n{"type":"stop"}\n');
    else child.kill('SIGTERM');
    while (await ownerAlive(record.tool)) {
      assert.ok(performance.now() - start < 1200, 'Tool cleanup must run while the output is blocked.');
      await new Promise(resolve => setTimeout(resolve, 10));
    }
    const ended = await exited; assert.equal(ended.code, 2); assert.equal(ended.signal, null);
    assert.ok(performance.now() - start < 3000, 'Cancellation must finish within the scaled fifteen-second bound.');
    for (const path of [join(f.state, 'runs', 'backpressure.json'), join(f.state, 'tmp', 'backpressure')]) {
      await assert.rejects(stat(path), (error: any) => error.code === 'ENOENT');
    }
    child.stdout.destroy(); child.stdin.destroy(); clearTimeout(safety);
  });
});
