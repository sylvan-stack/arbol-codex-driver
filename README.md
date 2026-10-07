# Arbol Codex Driver

Arbol Codex Driver: the Arbol 2 Driver for Codex.

The base (SYL-79) and Subscription operations (SYL-81) are implemented: `info`,
settings validation, private state, and account creation, relabelling, removal,
sign-in/sign-out, status, usage and model catalogs. Inference runs are the next
task (SYL-86); their command names currently return `unsupported`.

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
refusal and forced removal; they do not claim real Codex inference coverage.

`dev stand-in <folder> -- <arguments>` plays C31's supported, old and missing
variants, C32's `info` variant, and the account scenarios selected by
`<folder>/scenario`. It records starts and account RPCs in `received.jsonl`,
including private-home/environment checks and request counts. Version evidence
is in the Artifact Corpus's
`research/base-info-2026-10-07.json`; the handshake comes from the first response
in `research/probe-scripts-2026-10-06/live/codex-all.json`. Older versions and
changed record values are synthetic test variants. Account RPC shapes come from
the same recorded runs, with synthetic failures, pagination and concurrency.

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
