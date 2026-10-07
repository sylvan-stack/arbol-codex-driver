# Arbol Codex Driver

Arbol Codex Driver: the Arbol 2 Driver for Codex.

The base (SYL-79), Subscription operations (SYL-81), fresh inference runs
(SYL-86), conversation continuity (SYL-88), and stopping and recovery (SYL-89)
are implemented. `run` validates its request and account, starts one
private-home app-server, streams answer and reasoning blocks with gapless
sequence numbers, reports token totals, and ends with one final event after
cleanup. Runs in progress are visible through `runs list`.

| | |
|---|---|
| Package | `@sylvan-stack/arbol-codex-driver` 1.0.0 |
| Artifact corpus | `~/Artifacts/arbol-codex-driver` (GitHub `sylvan-stack/arbol-codex-driver-artifacts`) |

## Development

Use Node.js 24 or later. Run `npm ci`, then `npm run build`. Start the program with
`node bin/arbol-codex-driver.mjs info`; `--state-dir <folder>` selects its state.
Settings are read from `~/.arbol/arbol-codex-driver.json` on every invocation.
`toolPath` names a Codex executable, otherwise it is found on `PATH`. The oldest
supported version is `codex-cli 0.159.2`. The version probe uses a temporary home
and a clean environment; it sends no prompt.

`npm test` runs the unit checks. With the sibling `arbol` repository compiled,
`node test/conformance-base.mjs ../arbol` runs shared C31 and C32's `info` check.
`node test/conformance-subscriptions.mjs ../arbol` runs ten account scenarios,
with explicit subscription scopes for C4, C5, C7, C8 and C40. Full inference
scenarios belong to later tasks. Synthetic active-run tests verify account
refusal and forced removal; real fresh-run checks are separate.

`node test/conformance-runs.mjs ../arbol` runs eleven fresh-run scenarios, with
explicit scopes for C33 (no control input and stdin request) and C40 (fresh-run
refusals). The shared checks inspect native Codex RPCs as well as Claude input.
Focused integration tests cover images, settings defaults, control refusals,
stdout closure, account rechecks, and run-record cleanup.

For example:

```sh
node bin/arbol-codex-driver.mjs run --subscription test-chatgpt \
  --model gpt-5.6-luna --effort low "Reply with hello."
```

This uses an ephemeral thread in an empty folder removed when the run ends.
`--request <file>` accepts the contract's JSON request, and CLI values override
it. Images become private temporary `localImage` files. `--output text` prints
complete answer blocks only. Use `--tools all --cwd <absolute-folder>` for
unrestricted tools. A run whose tools are `none` uses Codex's read-only sandbox
with network access off; Codex may still use a tool, whose calls are reported
normally. Only Codex memories are switched off in its feature configuration.

With a chat identifier and working folder, a completed run maps the caller's
conversation to Codex's saved thread. The map stores identifiers, message counts
and SHA-256 digests. Matching history resumes that thread in the new app-server;
changed history, folder or system prompt rebuilds it with one native
`thread/inject_items` request, including tool results and pictures. `started`
reports the continuity and rebuild reason. If Codex refuses native history, a
notice reports the labelled text fallback. Failed and cancelled resumed runs
invalidate their map entry while preserving a newer concurrent completion.
Runs without a working folder use ephemeral threads and leave no map entry.

`node test/conformance-continuity.mjs ../arbol` runs shared C14 against the Codex
stand-in. Focused unit and integration checks cover digests, all rebuild reasons,
native and text histories, private image files, model overrides, concurrent
resumes and map invalidation.

Stop a run with `runs stop <run-id>`, an interrupt or termination signal, or a
`{"type":"stop"}` line on the standard input of `run --control`. Ending that
control input or losing the event output also stops the run. `runs stop` waits
for its final event and succeeds for an ended or unknown run. A stop preserves
events already sent, closes running calls as interrupted, and ends as
`cancelled` with exit status 2.

The Driver interrupts the main turn and active sub-agent turns concurrently
under one two-second deadline. It then closes app-server input and ends any
remaining verified process groups within the fifteen-second stop bound. Run
records and temporary files go after cleanup. If the Driver is killed outright,
the next `run`, `runs list`, `runs stop` or Subscription change recovers the
orphaned tool and its command groups, removes its temporary folder and record,
and invalidates the matching conversation entry. A program that makes itself a
separate background service is outside this cleanup, as DRV-D33 specifies.

`node test/conformance-stops.mjs ../arbol` runs shared C15, C16, C17, C38 and
C33's active-record and peer-stop checks. Caller questions remain excluded from
Codex's C33 scope. Focused tests cover control and signal stops, event-pipe loss,
ignored interrupts, active child and descendant turns, process identities,
simultaneous recovery and conditional conversation invalidation. Full owner
tools and sub-agent routing (SYL-90), and vendor error classification and
inference time limits (SYL-91), remain later tasks.

`dev stand-in <folder> -- <arguments>` plays C31's supported, old and missing
variants, C32's `info` variant, and the account scenarios selected by
`<folder>/scenario`. It records starts and account RPCs in `received.jsonl`,
including private-home/environment checks and request counts. Version evidence
is in the Artifact Corpus's
`research/base-info-2026-10-07.json`; the handshake comes from the first response
in `research/probe-scripts-2026-10-06/live/codex-all.json`. Older versions and
changed record values are synthetic test variants. Account and run RPC shapes
come from the same recorded runs, with synthetic failures, pagination,
concurrency, usage counts and oversized output.

Every account child uses its Subscription's private `CODEX_HOME`; Codex keeps
and renews the login there. Sign-in lasts in one command and emits JSON lines.
Use `subscriptions sign-in <id> --by-code` for a device code. Replacing a login,
ending its command or reaching five minutes cancels it and cleans up its child.
Status checks renew through Codex, usage caches the last good report, and model
catalogs include the tool's efforts and service tiers, with a marked built-in
fallback. The Driver never reads or copies a credential file.

The opt-in `test/probe-subscriptions.mjs <codex-path> <test-chatgpt-home>
<record-path>` sends no prompts. It checks configuration, both login methods,
local replacement and cleanup in fresh homes, then account status, usage and
models in the pre-authorized test home. It creates a local account record from
Codex's confirmed account details when that home has no record yet. It preserves
the test login and omits the account's email from its saved evidence. The latest
record is `research/subscriptions-2026-10-07.json` in the Artifact Corpus.

The opt-in `test/probe-run-protocol.mjs <codex-path> <record-path>` sends no
prompt: it checks the installed stable schema, local image form, configuration,
handshake and cleanup. `test/probe-run.mjs <codex-path> <state-dir> <record-path>`
sends two short low-effort Luna messages on `test-chatgpt`, checks events and
usage, and verifies temporary-folder and record cleanup. Their evidence is in
`research/run-protocol-2026-10-07.json` and `research/run-2026-10-07.json`.

`test/probe-continuity.mjs <codex-path> <record-path>` sends no prompt and checks
the stable resume/injection schema, tool-created history, pictures, tool names
and resume notifications in a fresh private home. The opt-in
`test/probe-continuity-live.mjs <codex-path> <state-dir> <record-path>` sends four
short Luna turns at the lowest offered effort on `test-chatgpt`: a tool turn,
a resumed follow-up, an edited-history rebuild and a changed-system-prompt
rebuild. Records are `research/continuity-protocol-2026-10-07.json` and
`research/continuity-2026-10-07.json`.

`test/probe-stop.mjs <codex-path> <record-path>` sends no prompt or account
request. It checks the stable interrupt and sub-agent notification schemas, an
idle interrupt, continued transport use and EOF cleanup in a fresh home. The
opt-in `test/probe-stop-live.mjs <codex-path> <state-dir> <record-path>` checks
answer cancellation, stopping a sub-agent's long command and recovery after a
killed Driver on `test-chatgpt`, after checking available usage. Evidence is
saved as `research/stopping-protocol-2026-10-07.json` and
`research/stopping-2026-10-07.json` in the Artifact Corpus.

Package version and build number are separate. A source checkout reports build
`0`; a copied Build reads `build.json` beside its package. Build selection is the
job of the `arbol-builds` launcher. The first working numbered Codex Build is
covered by SYL-94.

## Sylvan Stack 2

| Repository | Package | Version | Artifact corpus | Artifact repository |
|---|---|---|---|---|
| `arbol` | `@sylvan-stack/arbol` | 2.0.0 | `~/Artifacts/arbol` | `sylvan-stack/arbol-artifacts` |
| `arbol-root` | `@sylvan-stack/arbol-root` | 1.0.0 | `~/Artifacts/arbol-root` | `sylvan-stack/arbol-root-artifacts` |
| `arbol-trunk` | `@sylvan-stack/arbol-trunk` | 1.0.0 | `~/Artifacts/arbol-trunk` | `sylvan-stack/arbol-trunk-artifacts` |
| `arbol-claude-driver` | `@sylvan-stack/arbol-claude-driver` | 1.0.0 | `~/Artifacts/arbol-claude-driver` | `sylvan-stack/arbol-claude-driver-artifacts` |
| `arbol-codex-driver` | `@sylvan-stack/arbol-codex-driver` | 1.0.0 | `~/Artifacts/arbol-codex-driver` | `sylvan-stack/arbol-codex-driver-artifacts` |
| `mycel` | `@sylvan-stack/mycel` | 2.0.0 | `~/Artifacts/mycel` | `sylvan-stack/mycel-artifacts` |
