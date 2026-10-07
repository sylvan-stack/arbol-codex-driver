// SYL-88 exercises the shared history and continuity scenario with the Codex
// app-server stand-in. No vendor inference or credentials are used.
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
const suite = resolve(process.argv[2] ?? '../arbol');
const { runSuite } = await import(pathToFileURL(resolve(suite, 'dist/conformance/runner.js')));
const { c14 } = await import(pathToFileURL(resolve(suite, 'dist/conformance/scenarios/c14.js')));
const cli = resolve(import.meta.dirname, '../bin/arbol-codex-driver.mjs');
process.exitCode = await runSuite([process.execPath, cli], [c14]);
