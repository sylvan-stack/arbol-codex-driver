import { readFile, appendFile, writeFile, rm, stat } from 'node:fs/promises';
import { join } from 'node:path';
import { createInterface } from 'node:readline';
import { Failure } from './errors.js';
import { isObject } from './settings.js';
import { runStandIn } from './run-stand-in.js';

// Version line: research/base-info-2026-10-07.json (codex-cli 0.159.2).
// Initialize envelope: the first response in the recorded 6 October run,
// ~/Artifacts/arbol-codex-driver/research/probe-scripts-2026-10-06/live/codex-all.json.
// Account/model/rate-limit envelopes: requests 2–4 and 11 in that recording.
// Login start/completion: signin/login_codex.py in the same probe folder and
// research/tool-probes-2026-10-05.md. Credentials, account values, pagination,
// unavailable/rejected responses, and short/session windows are synthetic
// variants; they are deliberately not presented as additional probe evidence.
export const scripts = {
  C31: { supported: '0.159.2', old: '0.159.1', missing: undefined },
  C32: { info: '0.159.2' },
};

const subscriptionScenarios = ['C1', 'C2', 'C4', 'C5', 'C6', 'C7', 'C8', 'C39', 'C40', 'C41'];
const subscriptionParts = ['supported', 'success', 'by-code', 'waiting', 'rejected', 'unavailable', 'failed', 'wrong-home', 'other-account', 'unknown-windows'];
const protocolSource = '~/Artifacts/arbol-codex-driver/research/probe-scripts-2026-10-06/live/codex-all.json';
const fixtureAccount = { type: 'chatgpt', email: 'fixture@example.invalid', planType: 'fixture' };
const fixtureModels = [
  { id: 'gpt-6.1-sol', model: 'gpt-6.1-sol', displayName: 'GPT-6.1-Sol', description: 'Latest workhorse model for coding and everyday work.',
    hidden: false, supportedReasoningEfforts: ['low', 'medium', 'high', 'xhigh', 'max', 'ultra'].map(reasoningEffort => ({ reasoningEffort, description: 'Fixture effort' })),
    defaultReasoningEffort: 'low', serviceTiers: [{ id: 'priority', name: 'Fast', description: '2x speed, increased usage' }], isDefault: true },
  { id: 'gpt-6-astra', model: 'gpt-6-astra', displayName: 'GPT-6-Astra', description: 'Frontier intelligence for the most demanding work.',
    hidden: false, supportedReasoningEfforts: ['low', 'medium', 'high', 'xhigh', 'max', 'ultra'].map(reasoningEffort => ({ reasoningEffort, description: 'Fixture effort' })),
    defaultReasoningEffort: 'medium', serviceTiers: [{ id: 'priority', name: 'Fast', description: '2x speed, increased usage' }], isDefault: false },
];
const operation = (method: unknown): string => method === 'account/rateLimits/read' ? 'usage' : method === 'model/list' ? 'models' :
  method === 'account/read' ? 'check' : method === 'account/login/start' ? 'sign-in' : method === 'account/logout' ? 'sign-out' :
  method === 'account/login/cancel' ? 'cancel-sign-in' : ['initialize', 'initialized', 'config/read'].includes(String(method)) ? 'setup' : 'unsupported';

export async function standIn(folder: string, args: string[]): Promise<number> {
  const [scenario, part = 'supported', ...extra] = (await readFile(join(folder, 'scenario'), 'utf8')).trim().split(/\s+/);
  if (['C10', 'C11', 'C12', 'C13', 'C18', 'C19', 'C20', 'C33', 'C42', 'C43'].includes(scenario!) || scenario === 'C40' && !subscriptionParts.includes(part)) return runStandIn(folder, args);
  const subscriptions = subscriptionScenarios.includes(scenario!);
  const known = scenario === 'C31' && ['supported', 'old', 'missing'].includes(part) || scenario === 'C32' && part === 'info' || subscriptions && subscriptionParts.includes(part);
  if (extra.length || !known) throw new Failure('invalid_input', 'This stand-in does not implement that scenario.');
  const version = subscriptions ? scripts.C31.supported : scenario === 'C32' ? scripts.C32.info : scripts.C31[part as keyof typeof scripts.C31];
  const home = process.env.CODEX_HOME;
  const credential = home ? join(home, 'auth.json') : undefined;
  let loggedIn = credential ? await readFile(credential, 'utf8').then(() => true).catch(() => false) : false;
  const record = {
    scenario, part, arguments: args, environment: Object.keys(process.env).sort(), workingDirectory: process.cwd(),
    toolVersion: version ?? null, checks: subscriptions ? {
      home: home ?? null,
      privateHome: !!home && await stat(home).then(value => (value.mode & 0o077) === 0).catch(() => false),
      source: protocolSource,
      synthetic: 'Successful login, account data, cursor, limit-window and failure variants of the recorded protocol',
      injectedVariablesAbsent: Object.keys(process.env).every(name => !name.startsWith('OPENAI_') && (!name.startsWith('CODEX_') || name === 'CODEX_HOME') &&
        !['ANTHROPIC_API_KEY', 'CLAUDECODE', 'CLAUDE_SESSION_ID', 'NODE_OPTIONS'].includes(name)),
      hasCredential: loggedIn,
    } : {},
  };
  const received = async (extra: Record<string, unknown> = {}) => appendFile(join(folder, 'received.jsonl'), JSON.stringify({ ...record, ...extra }) + '\n', { mode: 0o600 });
  await received();
  if (!version) return 127;
  if (args.length === 1 && args[0] === '--version') {
    process.stdout.write(`codex-cli ${version}\n`);
    return 0;
  }
  if (args.length !== 1 || args[0] !== 'app-server') throw new Failure('unsupported', 'This stand-in implements only the version probe and app-server.');
  const lines = createInterface({ input: process.stdin });
  let initialized = false;
  let loginId: string | undefined;
  let completion: ReturnType<typeof setTimeout> | undefined;
  const write = (value: unknown) => process.stdout.write(JSON.stringify(value) + '\n');
  const notify = (method: string, params: unknown) => write({ method, params });
  for await (const line of lines) {
    const request: unknown = JSON.parse(line);
    if (!isObject(request)) continue;
    if (subscriptions) await received({ stage: 'request', request, checks: { ...record.checks, operation: operation(request.method) } });
    if (!('id' in request)) continue;
    const answer = (result: unknown) => write({ id: request.id, result });
    const error = (message: string, code = -32600) => write({ id: request.id, error: { code, message } });
    if (request.method === 'initialize' && !initialized) {
      initialized = true;
      answer({
        userAgent: `arbol-codex-driver/${version} (Mac OS 27.0.1; arm64) unknown (arbol-codex-driver; 1.0.0)`,
        codexHome: part === 'wrong-home' ? join(folder, 'wrong-home') : process.env.CODEX_HOME ?? process.env.HOME, platformFamily: 'unix', platformOs: 'macos',
      });
    } else if (!initialized) error('Not initialized');
    else if (subscriptions && home && credential) {
      const params = isObject(request.params) ? request.params : {};
      switch (request.method) {
        case 'config/read':
          answer({ config: { check_for_update_on_startup: false, web_search: 'live', cli_auth_credentials_store: 'file', analytics: { enabled: false }, features: { memories: false } }, origins: {}, layers: null });
          break;
        case 'account/login/start': {
          if (params.type !== 'chatgpt' && params.type !== 'chatgptDeviceCode') { error('Unsupported login type', -32602); break; }
          if (loginId) {
            notify('account/login/completed', { loginId, success: false, error: 'Login server error: Login cancelled', onboardingEntrypoint: null });
            if (completion) clearTimeout(completion);
          }
          loginId = `fixture-login-${process.pid}`;
          const device = params.type === 'chatgptDeviceCode';
          answer(device ? { type: 'chatgptDeviceCode', loginId, verificationUrl: 'https://auth.openai.com/codex/device', userCode: 'FIXT-12345' } :
            { type: 'chatgpt', loginId, authUrl: `https://auth.openai.com/oauth/authorize?redirect_uri=http%3A%2F%2F127.0.0.1%3A1455%2Fauth%2Fcallback&state=${loginId}` });
          if (part !== 'waiting') completion = setTimeout(() => {
            const current = loginId;
            if (!current) return;
            void (async () => {
              if (part !== 'failed') { await writeFile(credential, JSON.stringify({ credential: 'fixture-vendor-secret' }), { mode: 0o600 }); loggedIn = true; }
              loginId = undefined;
              notify('account/login/completed', { loginId: current, success: part !== 'failed', error: part === 'failed' ? 'Login server error: Login cancelled' : null, onboardingEntrypoint: null });
              if (part !== 'failed') notify('account/updated', { authMode: 'chatgpt', planType: fixtureAccount.planType });
            })();
          }, 75);
          break;
        }
        case 'account/login/cancel': {
          const current = loginId;
          if (!current || params.loginId !== current) { answer({ status: 'notFound' }); break; }
          if (completion) clearTimeout(completion); loginId = undefined;
          answer({ status: 'canceled' });
          notify('account/login/completed', { loginId: current, success: false, error: 'Login server error: Login was not completed', onboardingEntrypoint: null });
          break;
        }
        case 'account/read':
          if (part === 'unavailable') { error('Fixture account service unavailable', -32000); break; }
          answer({ account: loggedIn && part !== 'rejected' ? part === 'other-account' ? { type: 'apiKey' } : fixtureAccount : null,
            requiresOpenaiAuth: true, workspaceRouting: { chatgptAccountId: '00000000-0000-0000-0000-000000000000', backendOrigin: 'https://chatgpt.com', accountRoutingOverride: 'NO_CONSTRAINT' } });
          break;
        case 'account/logout':
          await rm(credential, { force: true }); loggedIn = false; answer({});
          notify('account/updated', { authMode: null, planType: null });
          break;
        case 'account/rateLimits/read': {
          if (part === 'rejected') { error('Authentication failed: ChatGPT login expired; please log in again.', -32000); break; }
          if (part === 'unavailable') { error('Fixture usage service temporarily unavailable', -32000); break; }
          const limits = { limitId: 'codex', limitName: null, normalModelSlug: null,
            primary: part === 'unknown-windows' ? { usedPercent: 7, windowDurationMins: null, resetsAt: null } : { usedPercent: 25, windowDurationMins: 10080, resetsAt: 1791640848 },
            secondary: part === 'unknown-windows' ? { usedPercent: 100, windowDurationMins: 1440, resetsAt: null } : { usedPercent: 100, windowDurationMins: 300, resetsAt: null },
            credits: { hasCredits: false, unlimited: false, balance: '0' }, individualLimit: null,
            spendControlReached: false, planType: 'fixture', rateLimitReachedType: null };
          answer({ ordinaryUsageAllowed: true, rateLimits: limits, rateLimitsByLimitId: { codex: limits }, rateLimitResetCredits: { availableCount: 0, credits: [] }, accountId: '00000000-0000-0000-0000-000000000000', rateLimitUpsell: null });
          break;
        }
        case 'model/list':
          if (part === 'unavailable') { error('Fixture model service temporarily unavailable', -32000); break; }
          if (params.includeHidden !== false) { error('The fixture requires hidden models to be excluded', -32602); break; }
          if (params.cursor === undefined || params.cursor === null) answer({ data: [fixtureModels[0]], nextCursor: 'fixture-page-2' });
          else if (params.cursor === 'fixture-page-2') answer({ data: [fixtureModels[1]], nextCursor: null });
          else error('Unknown model cursor', -32602);
          break;
        default: error('This stand-in implements only Subscription app-server requests.', -32601);
      }
    } else error('This stand-in implements only initialize.');
  }
  if (completion) clearTimeout(completion);
  return 0;
}
