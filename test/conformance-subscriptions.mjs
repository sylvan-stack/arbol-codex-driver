// SYL-81 implements account operations; full run scenarios remain in the shared
// suite for Drivers whose inference tasks are complete. Keep partial scopes in
// the report so a passing subscription check cannot imply passing run coverage.
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
const suite = resolve(process.argv[2] ?? '../arbol');
const { runSuite } = await import(pathToFileURL(resolve(suite, 'dist/conformance/runner.js')));
const { c1 } = await import(pathToFileURL(resolve(suite, 'dist/conformance/scenarios/c1.js')));
const {
  c2, c4, c5, c6, c7, c8, c39, c41,
  checkSubscriptionRejection, checkSubscriptionRemoval, checkSubscriptionCredentials, checkSubscriptionEnvironments,
} = await import(pathToFileURL(resolve(suite, 'dist/conformance/scenarios/subscriptions.js')));
const { c40, checkSubscriptionRefusals } = await import(pathToFileURL(resolve(suite, 'dist/conformance/scenarios/c40.js')));
const cli = process.env.ARBOL_DRIVER_ENTRY ?? resolve(import.meta.dirname, '../bin/arbol-codex-driver');
process.exitCode = await runSuite([cli], [
  c1, c2,
  { ...c4, scope: 'subscription check rejection and recovery only (SYL-81)', covers: ['DRV-1.7 (check)', 'DRV-1.11 (attention check)'], run: checkSubscriptionRejection },
  { ...c5, scope: 'sign-out, account clearing and home removal only (SYL-81)', covers: ['DRV-1.12 (without runs)', 'DRV-1.13'], run: checkSubscriptionRemoval },
  c6,
  { ...c7, scope: 'subscription operations and tool-owned login only (SYL-81)', covers: ['DRV-0.3 (subscriptions)', 'DRV-1.3 (subscriptions)', 'DRV-1.8'], run: checkSubscriptionCredentials },
  { ...c8, scope: 'sign-in, status, usage and catalog children only (SYL-81)', covers: ['DRV-0.5 (subscriptions)'], run: checkSubscriptionEnvironments },
  c39,
  { ...c40, scope: 'unsigned models, check and usage only (SYL-81)', covers: ['DRV-1.11 (subscription operations)'], run: checkSubscriptionRefusals },
  c41,
]);
