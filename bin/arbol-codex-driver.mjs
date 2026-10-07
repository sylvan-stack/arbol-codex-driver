#!/usr/bin/env node
import { main, outputWasAbandoned } from '../dist/src/cli.js';
process.exitCode = await main(process.argv.slice(2));
// Node's stdout wrapper can retain a blocked write after destroy(). The runner
// has already ended its processes and removed its record before returning.
if (outputWasAbandoned) process.exit(process.exitCode);
