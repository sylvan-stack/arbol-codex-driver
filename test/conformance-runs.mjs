// SYL-86 covers fresh runs. Interactive questions, continuity and cancellation
// belong to later tasks; their limited scenarios retain explicit report scopes.
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
const suite = resolve(process.argv[2] ?? '../arbol');
const { runSuite } = await import(pathToFileURL(resolve(suite, 'dist/conformance/runner.js')));
const { c10, c11, c12, c13, c18, c19, c20, c33, c42, c43, checkRunWithoutControl, runRefusals } =
  await import(pathToFileURL(resolve(suite, 'dist/conformance/scenarios/runs.js')));
const { c40, checkSubscriptionRefusals } = await import(pathToFileURL(resolve(suite, 'dist/conformance/scenarios/c40.js')));
const cli = process.env.ARBOL_DRIVER_ENTRY ?? resolve(import.meta.dirname, '../bin/arbol-codex-driver');
process.exitCode = await runSuite([cli], [
  c10, c11, c12, c13, c18, c19, c20,
  { ...c33, scope: 'no control input and JSON request from stdin only (SYL-86)', covers: ['DRV-2.25', 'DRV-6.7 (request stdin)'], run: checkRunWithoutControl },
  { ...c40, scope: 'unsigned runs and fresh-run directory, duplicate ID, model, effort and tier refusals (SYL-86)',
    covers: ['DRV-1.11 (unsigned runs)', 'DRV-2.2'], async run(home) { await checkSubscriptionRefusals(home, true); await runRefusals(home); } },
  c42, c43,
]);
