// SYL-92: every accepted shared scenario through the packaged offline stand-in.
// No scenario filters or assertion changes are applied by this wrapper.
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
const suite = resolve(process.argv[2] ?? '../arbol');
const { runSuite } = await import(pathToFileURL(resolve(suite, 'dist/conformance/runner.js')));
const { scenarios } = await import(pathToFileURL(resolve(suite, 'dist/conformance/scenarios/index.js')));
const cli = process.env.ARBOL_DRIVER_ENTRY ?? resolve(import.meta.dirname, '../bin/arbol-codex-driver');
process.exitCode = await runSuite([cli], scenarios);
