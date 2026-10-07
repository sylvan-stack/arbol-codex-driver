import { homedir } from 'node:os';
import { resolve } from 'node:path';
import { parseArguments } from './arguments.js';
import { Failure, safeFailure } from './errors.js';
import { readSettings, settingsPath } from './settings.js';
import { buildIdentity } from './build.js';
import { State, defaultStateDirectory, fixedWait } from './state.js';
import { inspectTool, requireTool } from './tool.js';
import { standIn } from './stand-in.js';
import { Subscriptions, families } from './subscriptions.js';
import { EventStream } from './event-stream.js';
import { run } from './run.js';
import { Runs } from './runs.js';

export async function main(args: string[]): Promise<number> {
  const operation = args.filter((arg, index) => arg !== '--state-dir' && args[index - 1] !== '--state-dir' && !arg.startsWith('--state-dir='))[0];
  const events = operation === 'run' ? new EventStream() : undefined;
  const cancellation = new AbortController();
  const stop = (): void => cancellation.abort();
  process.on('SIGINT', stop);
  process.on('SIGTERM', stop);
  try {
    if (Number(process.versions.node.split('.')[0]) < 24) throw new Failure('unsupported', 'This Driver needs Node.js 24 or later.');
    const command = parseArguments(args);
    // The suite's executable reads only its scenario, never Driver settings or state.
    if (command.name === 'dev stand-in') return await standIn(resolve(command.positionals[0]!), command.positionals.slice(2));
    fixedWait(1); // Refuse an invalid test scale before creating state.
    const home = process.env.HOME || homedir();
    const file = settingsPath(home);
    const { settings, notices } = await readSettings(file);
    const state = new State(typeof command.options['state-dir'] === 'string' ? command.options['state-dir'] : defaultStateDirectory(home));
    await state.initialize();
    if (command.name === 'run' || ['subscriptions create', 'subscriptions update', 'subscriptions remove',
      'subscriptions sign-in', 'subscriptions sign-out', 'subscriptions check', 'subscriptions usage', 'subscriptions models'].includes(command.name)) {
      await new Runs(state).list();
    }
    const identity = await buildIdentity();
    cancellation.signal.throwIfAborted();
    if (command.name === 'run') return await run(command, new Subscriptions(state, settings, notices, file, process.env, cancellation.signal), events!, process.env, identity.build, cancellation.signal);
    if (command.name === 'runs list') {
      const records = await new Runs(state).list();
      process.stdout.write(JSON.stringify(records.map(({ runId, subscriptionId, startedAt, labels }) => ({ runId, subscriptionId, startedAt, ...(labels === undefined ? {} : { labels }) }))) + '\n'); return 0;
    }
    if (command.name === 'runs stop') { await new Runs(state).stop(command.positionals[0]!); return 0; }
    if (command.name === 'info') {
      const tool = await inspectTool(state, settings.toolPath, process.env, cancellation.signal);
      cancellation.signal.throwIfAborted();
      process.stdout.write(JSON.stringify({ driver: 'codex', ...identity, contract: 1, stateDirectory: state.directory, settingsFile: file, tool,
        ...(notices.length ? { notices } : {}) }) + '\n');
      return 0;
    }
    if (command.name.startsWith('subscriptions ')) {
      const subscriptions = new Subscriptions(state, settings, notices, file, process.env, cancellation.signal);
      const id = command.positionals[0]!;
      let result: unknown;
      switch (command.name) {
        case 'subscriptions families': result = families; break;
        case 'subscriptions list': result = await subscriptions.list(); break;
        case 'subscriptions create': result = await subscriptions.create(command.options.family, command.options.label, command.options.id as string | undefined); break;
        case 'subscriptions update': result = await subscriptions.update(id, command.options.label as string | undefined); break;
        case 'subscriptions remove': await subscriptions.remove(id, command.options.force === true); return 0;
        case 'subscriptions sign-in': return await subscriptions.signIn(id, command.options['by-code'] === true, step => process.stdout.write(JSON.stringify(step) + '\n'));
        case 'subscriptions sign-out': result = await subscriptions.signOut(id, command.options.force === true); break;
        case 'subscriptions check': result = await subscriptions.check(id); break;
        case 'subscriptions usage': result = await subscriptions.usage(id); break;
        case 'subscriptions models': result = await subscriptions.models(id); break;
        default: throw new Failure('unsupported', 'This Subscription command is not supported by the Codex Driver.');
      }
      cancellation.signal.throwIfAborted();
      if (notices.length && result !== null && typeof result === 'object' && !Array.isArray(result)) result = { ...result, notices };
      process.stdout.write(JSON.stringify(result) + '\n'); return 0;
    }
    if (command.toolRequired) requireTool(await inspectTool(state, settings.toolPath, process.env, cancellation.signal));
    throw new Failure('unsupported', `Command ${command.name} is not implemented in this Driver yet.`);
  } catch (error) {
    if (events) return events.finish(error, cancellation.signal.aborted).catch(() => 2);
    if (cancellation.signal.aborted) return 2;
    process.stdout.write(JSON.stringify({ error: safeFailure(error) }) + '\n');
    return 1;
  } finally {
    process.off('SIGINT', stop);
    process.off('SIGTERM', stop);
  }
}
