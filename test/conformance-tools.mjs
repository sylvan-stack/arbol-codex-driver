// SYL-90: shared offline advanced tools and owner setup checks. Vendor shapes
// come from retained protocol evidence; no credentials or inference are used.
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
const suite = resolve(process.argv[2] ?? '../arbol');
const { runSuite } = await import(pathToFileURL(resolve(suite, 'dist/conformance/runner.js')));
const { c9, c25, c35, c37 } = await import(pathToFileURL(resolve(suite, 'dist/conformance/scenarios/tools.js')));
const cli = process.env.ARBOL_DRIVER_ENTRY ?? resolve(import.meta.dirname, '../bin/arbol-codex-driver');
process.exitCode = await runSuite([cli], [
  { ...c9, scope: 'owner Codex setup and agent skills unchanged; only MCP tables forwarded in memory' },
  { ...c25, scope: 'command/file approvals accepted; permissions, client tools, MCP and caller questions rejected; malformed protocol affects only its run' },
  { ...c35, scope: 'shell refusal, patch/web/MCP shape, both child announcements, nested children and completed late command; no-tools unexpected call' },
  { ...c37, scope: 'owner skills discovered, exact secret-bearing MCP tables forwarded, private setup isolated, no-tools MCP omission' },
]);
