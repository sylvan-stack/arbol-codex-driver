// C32 also exercises later tasks. Run its existing shared info check explicitly.
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
const suite = resolve(process.argv[2] ?? '../arbol');
const { runSuite } = await import(pathToFileURL(resolve(suite, 'dist/conformance/runner.js')));
const { c31 } = await import(pathToFileURL(resolve(suite, 'dist/conformance/scenarios/c31.js')));
const { c32, checkDriverInfo } = await import(pathToFileURL(resolve(suite, 'dist/conformance/scenarios/c32.js')));
const cli = resolve(import.meta.dirname, '../bin/arbol-codex-driver.mjs');
process.exitCode = await runSuite([process.execPath, cli], [c31,
  { ...c32, scope: 'info only (SYL-79)', covers: ['DRV-0.6', 'DRV-0.13', 'DRV-0.15'], run: checkDriverInfo },
]);
