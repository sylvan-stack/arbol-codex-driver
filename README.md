# Arbol Codex Driver

Arbol Codex Driver: the Arbol 2 Driver for Codex.

The base command-line program is implemented (SYL-79): `info`, settings validation,
private state files, process ownership and Subscription locks. Subscription
operations and inference runs are the next implementation tasks. Their command
names are accepted and currently return `unsupported`.

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
`node test/conformance-base.mjs ../arbol` runs shared C31 and only C32's `info`
check. The full C32 and remaining scenarios belong to later tasks.

`dev stand-in <folder> -- <arguments>` plays C31's supported, old and missing
variants, or C32's `info` variant, selected by `<folder>/scenario`. It records
starts in `received.jsonl` and currently speaks the version probe and app-server
handshake. Version evidence is in the Artifact Corpus's
`research/base-info-2026-10-07.json`; the handshake comes from the first response
in `research/probe-scripts-2026-10-06/live/codex-all.json`. Older versions and
changed record values are synthetic test variants.

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
