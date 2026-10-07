// SYL-91: shared offline errors, retry interruption, clocks and run usage.
// Recorded Codex envelopes with synthetic classes, limits and clock delays;
// no login credentials, model requests or live vendor calls are used.
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
const suite = resolve(process.argv[2] ?? '../arbol');
const { runSuite } = await import(pathToFileURL(resolve(suite, 'dist/conformance/runner.js')));
const { c26, c27, c28, c29, c30 } = await import(pathToFileURL(resolve(suite, 'dist/conformance/scenarios/errors.js')));
const { c4 } = await import(pathToFileURL(resolve(suite, 'dist/conformance/scenarios/subscriptions.js')));
const cli = process.env.ARBOL_DRIVER_ENTRY ?? resolve(import.meta.dirname, '../bin/arbol-codex-driver');
process.exitCode = await runSuite([cli], [
  c4,
  { ...c26, scope: 'all Codex error classes, connection status precedence, vendor JSON, wording fallback, absent result and handshake version' },
  { ...c27, scope: 'seconds, minutes, omitted wait and exhausted-window reset; exactly one limits read and no Driver retry' },
  { ...c28, scope: 'first rejected Codex retry interrupts once and marks the account; Codex offers no retry-count setting' },
  { ...c29, scope: 'start, silent idle, every-notification heartbeat, idle off, tool call, background command and total while busy; caller questions are unsupported (C25)' },
  { ...c30, scope: 'latest run usage and sparse-field preservation stored at completion; subscription list reads the cached report without a tool invocation' },
]);
