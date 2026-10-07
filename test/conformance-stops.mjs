// SYL-89 stopping and recovery. Codex exposes no caller questions (CDX-3.13),
// so C33 carries an explicit scope excluding Claude's unanswered ask fixture.
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
const suite = resolve(process.argv[2] ?? '../arbol');
const { runSuite } = await import(pathToFileURL(resolve(suite, 'dist/conformance/runner.js')));
const { c15, c16, c17, c38, waitFor } = await import(pathToFileURL(resolve(suite, 'dist/conformance/scenarios/stops.js')));
const { c33, checkRunWithoutControl, stream } = await import(pathToFileURL(resolve(suite, 'dist/conformance/scenarios/runs.js')));
const { check, equal } = await import(pathToFileURL(resolve(suite, 'dist/conformance/check.js')));
const cli = resolve(import.meta.dirname, '../bin/arbol-codex-driver.mjs');
const scopedC33 = { ...c33, scope: 'no control, stdin request, malformed control, active records and runs stop; caller questions excluded by CDX-3.13 (SYL-89)',
  covers: ['DRV-2.25', 'DRV-2.26', 'DRV-2.27', 'DRV-2.28', 'DRV-6.7', 'DRV-6.8'], async run(home) {
    const id = await checkRunWithoutControl(home);
    await home.part('plain'); const active = home.start(['run', '--subscription', id, '--run-id', 'visible-run', '--control', 'hold']);
    try {
      active.child.stdin.write('not-json\n'); active.send({ type: 'answer', askId: 'missing', answer: {} });
      await waitFor('Active run listed', async () => JSON.parse((await home.call(['runs', 'list'])).stdout)
        .some(run => run.runId === 'visible-run' && run.subscriptionId === id));
      const records = stream(await active.done); equal('Control refusals', records.filter(event => event.type === 'control_refused').length, 2);
    } finally { await active.dispose(); }
    equal('No ended runs listed', JSON.parse((await home.call(['runs', 'list'])).stdout), []);
    await home.part('stopping'); const stopped = home.start(['run', '--subscription', id, '--run-id', 'stop-from-peer', 'answer']);
    try {
      await waitFor('Run started before peer stop', async () => stopped.lines.some(event => event.type === 'started'));
      const reply = await home.call(['runs', 'stop', 'stop-from-peer']); equal('Peer stop exit', reply.status, 0); equal('Peer stop output', reply.stdout, '');
      stream(await stopped.done, 'cancelled'); check('Final emitted before stop returns', stopped.lines.at(-1)?.type === 'finished', 'finished', stopped.lines.at(-1));
    } finally { await stopped.dispose(); }
  } };
process.exitCode = await runSuite([process.execPath, cli], [c15, c16, c17, scopedC33, c38]);
