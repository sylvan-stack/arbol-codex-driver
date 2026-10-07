import { readFile, appendFile } from 'node:fs/promises';
import { join } from 'node:path';
import { createInterface } from 'node:readline';
import { Failure } from './errors.js';
import { isObject } from './settings.js';

// Version line: research/base-info-2026-10-07.json (codex-cli 0.159.2).
// Initialize envelope: the first response in the recorded 6 October run,
// ~/Artifacts/arbol-codex-driver/research/probe-scripts-2026-10-06/live/codex-all.json.
// The older version, platform/home/client names and refusal are synthetic variants.
export const scripts = {
  C31: { supported: '0.159.2', old: '0.159.1', missing: undefined },
  C32: { info: '0.159.2' },
};

export async function standIn(folder: string, args: string[]): Promise<number> {
  const [scenario, part = 'supported', ...extra] = (await readFile(join(folder, 'scenario'), 'utf8')).trim().split(/\s+/);
  const known = scenario === 'C31' && ['supported', 'old', 'missing'].includes(part) || scenario === 'C32' && part === 'info';
  if (extra.length || !known) throw new Failure('invalid_input', 'This stand-in does not implement that scenario.');
  const version = scenario === 'C32' ? scripts.C32.info : scripts.C31[part as keyof typeof scripts.C31];
  await appendFile(join(folder, 'received.jsonl'), JSON.stringify({
    scenario, part, arguments: args, environment: Object.keys(process.env).sort(), workingDirectory: process.cwd(),
    toolVersion: version ?? null, checks: {},
  }) + '\n', { mode: 0o600 });
  if (!version) return 127;
  if (args.length === 1 && args[0] === '--version') {
    process.stdout.write(`codex-cli ${version}\n`);
    return 0;
  }
  if (args.length !== 1 || args[0] !== 'app-server') throw new Failure('unsupported', 'This stand-in implements only the version probe and handshake.');
  const lines = createInterface({ input: process.stdin });
  let initialized = false;
  for await (const line of lines) {
    const request: unknown = JSON.parse(line);
    if (!isObject(request) || !('id' in request)) continue;
    if (request.method === 'initialize' && !initialized) {
      initialized = true;
      process.stdout.write(JSON.stringify({ id: request.id, result: {
        userAgent: `arbol-codex-driver/${version} (Mac OS 27.0.1; arm64) unknown (arbol-codex-driver; 1.0.0)`,
        codexHome: process.env.CODEX_HOME ?? process.env.HOME, platformFamily: 'unix', platformOs: 'macos',
      } }) + '\n');
    } else process.stdout.write(JSON.stringify({ id: request.id, error: { code: -32600,
      message: initialized ? 'This stand-in implements only initialize.' : 'Not initialized' } }) + '\n');
  }
  return 0;
}
