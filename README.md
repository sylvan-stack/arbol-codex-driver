# Arbol Codex Driver

Arbol Codex Driver: the Arbol 2 Driver for Codex.

The base (SYL-79), Subscription operations (SYL-81), fresh inference runs
(SYL-86), conversation continuity (SYL-88), stopping and recovery (SYL-89),
tools, child agents and owner setup (SYL-90), errors, retries, clocks and
run-derived usage (SYL-91), and packaged probes and conformance (SYL-92)
are implemented. `run` validates its request and account, starts one
native-home app-server for canonical `chatgpt`, streams answer and reasoning blocks with gapless
sequence numbers, reports token totals, and ends with one final event after
cleanup. Runs in progress are visible through `runs list`.

The canonical runnable Subscription is `chatgpt`. It uses the account the owner
signed in to directly in Codex, in the default native `~/.codex` profile. Arbol
does not start sign-in, sign-out or credential refresh. The compatibility
`subscriptions sign-in chatgpt` action refreshes local status from the existing
native account and accepts no authentication codes. Use `codex login status`
to check the native login. `dev probe` reads the installed tool version and
the native account status only; it starts no authentication.

Additional-account execution and new Subscription creation are refused. The
canonical record is protected from sign-out or removal in Arbol. Eligible
legacy records can be relabelled or retired locally, while their native homes
and credentials stay in place. The full Build and real-account qualification
belong to ABR-38. Current testing policy is in [TESTS.md](TESTS.md).

| | |
|---|---|
| Package | `@sylvan-stack/arbol-codex-driver` 1.0.0 |
| Artifact corpus | `~/Artifacts/arbol-codex-driver` (GitHub `sylvan-stack/arbol-codex-driver-artifacts`) |

## Identity source and qualification (15 November 2026)

ABR-34 implements the Browser Subscription identity producer in source. Its
implementation checks are static. Registered payload construction, complete
ordinary Build gates, native/provider behavior, independent final review and
ABR-38's shared qualification are still required before installed or Browser
use. No gate, state migration, accepted payload or runtime pass follows from
this source change. [The Beat](https://github.com/sylvan-stack/forester-artifacts/blob/main/sagas/sylvan-stack/arbol-browser/driver-subscription-identity/ABR-34.md)
records exact source checkpoints and the remaining qualification routes.

A qualified invocation uses the registered launcher/provider and exact immutable
payload. Direct invocation of the new source or copied new entry without live
admission refuses before Driver state access, including for format1. Normal commands and helpers
hold their independent component admission; state admission survives final
output and task/executor cleanup. The generic helper API is implemented, while
retained dev/archived qualification runner wiring belongs to ABR-38. No testing
workaround supplies production authority.

The exact local operation is:

```text
subscriptions identity <canonical-id> [--expect <generation>.<witness>]
```

The canonical native selector is `chatgpt`. Identity uses only the validated
local record or implicit built-in and format2 sidecars. It works independently
of sign-in and reads no native account, settings contents or application
database; it performs no run reaping or app-server request. Its revision1 proof
contains driver, canonical subscription, root generation and lifetime witness.
The tokens are independent of IDs, timestamps and auth changes. `--expect`
requires the exact captured pair; a mismatch requires explicit selection and
rebind. Arbol alone owns application UUIDs. Qualified `info` adds
`capabilities.subscriptionIdentity: 1` while retaining contract1, package
version and Build reporting without another tool check solely for capability.

New admitted state starts at format2. Existing format1 retains its legacy
record behavior and has no positive identity proof or automatic conversion.
The default is `~/.arbol/drivers/codex`;
`--state-dir` selects another state directory under the same component gate.
The active account remains in Codex’s default native profile. Older isolated
homes are retained as legacy data.
Root/per-Subscription evidence is separate from record.json. Relabeling and auth
changes preserve proof; removal/retirement and delayed writes use canonical
short locks, journals and captured lifetime checks. Pending or unsafe metadata
refuses proof instead of guessing continuity. The real native status refresh
uses the existing default home. Older authentication reservations with unknown
ownership stay fenced for recovery.

Offline operations are the four fixed Driver child commands `state upgrade`,
`state identity-reset`, `state restore` and `state identity-recover`, dispatched
only by the shared `arbol-builds driver-state execute` provider under closed,
drained, exclusive admission. Every child requires `--confirm-quiescent` and
absolute canonical paths for `--state-dir`, `--maintenance` and `--backup`;
upgrade also requires `--from-format 1`, restore alone requires an absolute
canonical `--source`, and targeted
recovery alone requires `--subscription <canonical-id> --retire`. A copied
receipt, environment pair or quiescence assertion alone cannot grant authority.
The exact live descriptor/context, epoch, payload and attempt must match.

Archives contain only declared format/identity/journal metadata with explicit
absence and immutable `before/manifest.json`; format1 restore also has
`conversion-before/manifest.json`. They contain no record/account/auth/home/chat
or guard/registry bytes. Upgrade publishes the format2 fence before proof and
resumes its journaled generation. Reset and supported restore settle the same
fresh context generation across retries. Targeted conservative retirement
leaves record/credential references unchanged and makes no claim that native
cleanup succeeded. The provider alone acknowledges the result and reopens
admission. Known restores invalidate previous bindings; unknown complete file
rollback has no stronger detection claim.

A registered Build stages the original pinned CPython3.14.8 runtime and exact
clean committed source under `<Build>/driver-payload`. Complete M
(`driver-payload-manifest.json`) inventories every descendant except its own
root M and D; D (`driver-capability.json`) binds the Build, commit/tree,
interpreter, entry/helpers/import roots and capabilities. Execution uses
`runtime/python/bin/python3.14 -ISB bin/entry.py` with absolute verified paths.
Existing root entry/runtime/scripts/test paths link to those same bytes, so
current gate command strings remain intact. Mutable Build record/log/last-start
stay outside M. Unregistered static candidates have no D or qualified acceptance.
Neither packaging declarations nor static inputs issue acceptance; ABR-38 binds
the final five-repository tuples and evidence separately.

Current implementation work uses test-free source syntax/type/lint checks.
[TESTS.md](TESTS.md) owns separately requested test/Build work and the complete
current gates. Historical workflows, test-profile examples and earlier
format1/Build0 observations below retain their original scope.

## Historical numbered Build workflow

`arbol-builds build arbol-codex-driver` packages the Driver into the next
hexadecimal Build number under
`~/Library/Application Support/Arbol/builds/arbol-codex-driver/` (SYL-94).
The repository's `arbol-build.json` installs locked development dependencies,
runs Ruff and strict mypy, and packages the pinned standalone CPython runtime.
Its three checks run the packaged unit tests, all 38 shared conformance
scenarios, and exactly one quota-checked ready message on `test-chatgpt`.
All must pass before the Build becomes `working` and the default.

The build tool writes the launcher to `~/.local/bin`; that folder must be on
PATH. The launcher is Python and needs no Node.js (SYL-165). With the build tool installed from the sibling
`arbol` repository and `uv` available, run:

```sh
arbol-builds build arbol-codex-driver
arbol-codex-driver info
arbol-builds list arbol-codex-driver
arbol-codex-driver -v 1 info
```

`info` reports both the selected Build number and package version `1.0.0`.
Without `-v`, the launcher selects the newest working Build. The example
selects Build `1` explicitly; select any available number shown by `list`.
Failed checks retain their Build number, record and log, and leave the previous
working default in place. Contract and state format remain `1`.
`ARBOL_CONFORMANCE_REPO` can name another shared-suite checkout;
The live check finds the signed-in `test-chatgpt` Subscription in its own test
state directory, `~/Library/Application Support/Arbol/drivers/arbol-codex-driver/`,
not in the default one; `ARBOL_BUILD_TEST_STATE_DIR` can name another absolute
Driver state directory with it (DRV-D41).

## Historical development and qualification notes

The runtime is stdlib-only Python. Development and packaged artifacts pin
CPython 3.14.8; the standalone interpreter comes from Python Build Standalone
release 20261003, with an archive SHA-256 in `scripts/python-distribution.json`.
Run `uv sync --locked --group dev`, then start `bin/arbol-codex-driver info`.
`--state-dir <folder>` selects state. The source entry directly executes its
private `.venv` interpreter; the packaged entry directly executes its own
interpreter, preserving arguments, signals, and the caller's working folder.
Normal invocation installs nothing and needs no Python, uv, npm, or Node on PATH.

Run the Python checks with:

```sh
uv run --locked python -m ruff check src/arbol_codex_driver tests scripts bin/entry.py
uv run --locked python -m mypy
PYTHONPATH=src uv run --locked python -m unittest discover -s tests -v
```

The pinned Ruff and strict mypy versions are development dependencies only.
The unit suite uses `unittest`; its synthetic vendor and worker processes also
use Python. The shared conformance suite in the sibling `arbol` repository is Python too:
`.venv/bin/python -I -B ../arbol/conformance/bin/arbol-conformance.py --driver bin/arbol-codex-driver` runs the complete registry,
`--only <ids>` a part of it, and `--driver` names a packaged executable instead.

Settings are read from `~/.arbol/arbol-codex-driver.json` on every invocation.
`toolPath` names a Codex executable, otherwise it is found on `PATH`. The oldest
supported version is `codex-cli 0.159.2`. The version probe uses a temporary home
and a clean environment; it sends no prompt.

With the sibling `arbol` repository, `--only C31,C32` runs shared C31 and C32.
`--only C1,C2,C4,C5,C6,C7,C8,C39,C40,C41` runs the ten account scenarios. The
full registry includes inference and every applicable shared scenario. Synthetic active-run
tests verify account
refusal and forced removal; real fresh-run checks are separate.

`--only C10,C11,C12,C13,C18,C19,C20,C33,C40,C42,C43` runs the eleven fresh-run
scenarios. The shared checks inspect native Codex RPCs as well as Claude input.
Focused integration tests cover images, settings defaults, control refusals,
stdout closure, account rechecks, and run-record cleanup.

For example:

```sh
bin/arbol-codex-driver run --subscription test-chatgpt \
  --model gpt-5.6-luna --effort low "Reply with hello."
```

This uses an ephemeral thread in an empty folder removed when the run ends.
`--request <file>` accepts the contract's JSON request, and CLI values override
it. Images become private temporary `localImage` files. `--output text` prints
complete answer blocks only. Use `--tools all --cwd <absolute-folder>` for
unrestricted tools. A run whose tools are `none` uses Codex's read-only sandbox
with network access off; Codex may still use a tool, whose calls are reported
normally. The app-server receives only the accepted per-process options:
`--disable memories -c check_for_update_on_startup=false -c analytics.enabled=false -c 'web_search="live"'`.
The Driver checks those effective values and the handshake home; it does not
force a credential-store setting or compare unrelated owner configuration.

With a chat identifier and working folder, a completed run maps the caller's
conversation to Codex's saved thread. The map stores identifiers, message counts
and SHA-256 digests. Matching history resumes that thread in the new app-server;
changed history, folder or system prompt rebuilds it with one native
`thread/inject_items` request, including tool results and pictures. `started`
reports the continuity and rebuild reason. If Codex refuses native history, a
notice reports the labelled text fallback. Failed and cancelled resumed runs
invalidate their map entry while preserving a newer concurrent completion.
Runs without a working folder use ephemeral threads and leave no map entry.

`--only C14` runs shared C14 against the Codex
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
records and temporary files go after cleanup. A reader that accepts no output
within the remaining stop budget cannot receive the final event; the Driver
still exits after cleanup. If the Driver is killed outright,
the next `run`, `runs list`, `runs stop` or Subscription change recovers the
orphaned tool and its command groups, removes its temporary folder and record,
and invalidates the matching conversation entry. A program that makes itself a
separate background service is outside this cleanup, as DRV-D33 specifies.

`--only C15,C16,C17,C33,C38` runs shared C15, C16, C17, C33 and C38; C33 checks
that Codex refuses a caller question as unsupported. Focused tests cover control and signal stops, event-pipe loss,
ignored interrupts, active child and descendant turns, process identities,
simultaneous recovery and conditional conversation invalidation. Full owner
tools and sub-agent routing are checked by the tools suite below. Error
classification and inference time limits are checked by the errors suite.

`--only C9,C25,C35,C37` runs shared C9, C25, C35 and C37.
Commands keep their plain shell input and vendor refusal reason; patches, web
search and MCP results retain their specified shapes. Child text, tool output,
usage and notices carry the call that started the child, including notifications
that arrive before its receiver thread is announced. The run waits for child
turns and background commands, and gives other open calls, including child
calls, their two-second completion grace.

A tools-enabled run uses the owner's native Codex settings, hooks, plug-ins,
skills, MCP servers and instructions. The Driver reads only the MCP tables from
`~/.codex/config.toml` to learn private strings for output redaction; it forwards
no tables in `thread/start` or `thread/resume` and writes none. Missing,
unreadable or malformed setup supplies no scrub strings and leaves validation
to Codex. Known table strings are scrubbed from events and plain text output,
including values split across streamed chunks. Assistant fingerprints use the
redacted answer the caller receives. No skill links, setup copies or native
session-file scans are made. Codex itself discovers the owner's setup through
its native home and the real HOME. An MCP server needing its own
sign-in can report that; its sign-in workflow remains unspecified.

The explicit checks `scripts/check_tools.py probe --output <file>` and
`scripts/check_tools.py live --output <file>` use the checkout's Python.
The probe sends no inference request and verifies skills, thread-local MCP
startup, private configuration and owner-tree metadata. The live check uses
only `test-chatgpt` in the existing test state folder, `gpt-5.6-luna` at low
effort, and one short request for file/network access, a child agent and a
background command. Neither command runs in the offline unit suite.
Current evidence, including unsuccessful attempts, is in the Artifact Corpus's
`research/tools-2026-10-07/`.

`--only C4,C26,C27,C28,C29,C30` runs shared C4 and C26 to C30.
Failures use Codex's structured class and status before the permitted text
fallback. Every retry emits a notice; the first credential refusal interrupts
the run and marks its account `needs_attention`. A rate-limited failure makes
one quota-free limits read and reports a wait only when the vendor states one.
Runs apply the sixty-second startup budget, a fifteen-minute default idle
budget (zero disables it), and caller-specified total limits. Every notification
is a heartbeat; tool calls and background work suspend idle. Reached limits
use normal cleanup and finish `failed` with `limit_reached`.

The latest sparse account-limit notification is stored on completion, preserving
fields from fuller reports and protecting newer account changes and usage
reads. `scripts/check_errors.py probe --output <file>` checks unreachable-vendor
retries followed by caller cancellation with a loopback proxy. Its `live` mode
uses only `test-chatgpt`, `gpt-5.6-luna`, low effort and one tiny no-tools prompt
to check the saved report. Both require explicit invocation and use a clean
environment. Evidence is in `research/errors-2026-10-07/`; synthetic reached-limit
and overload fixtures remain distinct from live observations.

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

Historical isolated-account implementation, before the accepted native-home
boundary: every account child used its Subscription's private `CODEX_HOME`,
and Codex kept and renewed the login there. Those records and observations
remain recoverable. Current production account operations use the native
`chatgpt` binding described above. Sign-in still emits JSON lines and supports
`subscriptions sign-in chatgpt --by-code`; its existing timeout, attempt fences
and owned-child cleanup remain. Status/usage/model requests use the app-server,
and the Driver never reads or copies a credential file.

Recorded vendor evidence remains in the Artifact Corpus:
`research/base-info-2026-10-07.json`, `research/subscriptions-2026-10-07.json`,
`research/run-protocol-2026-10-07.json`, `research/run-2026-10-07.json`,
`research/continuity-protocol-2026-10-07.json`, `research/continuity-2026-10-07.json`,
and the stopping protocol, stopping, and stopping-subagent records from the
same date. These historical records preserve their original vendor shapes,
synthetic variations, failures, and subsequent corrections. Migration tests
include independent Node-generated format-1 history and JSON vectors; mixed
TypeScript/Python checks exercise the retained pre-migration program in both
directions. The former active TypeScript runtime, tests, and probe runners are
retained in Git history.

To rehearse a standalone development candidate without allocating a numbered
Build, create an empty folder and run:

```sh
uv run --locked python scripts/package_build.py --candidate /absolute/empty/folder
/absolute/empty/folder/runtime/python/bin/python3.14 /absolute/empty/folder/scripts/check_build.py metadata --candidate /absolute/empty/folder
/absolute/empty/folder/runtime/python/bin/python3.14 /absolute/empty/folder/scripts/check_build.py unit --candidate /absolute/empty/folder
```

The candidate contains its interpreter, runtime and tests.
Metadata checks validate the distribution and packaged file digests. The
registry rehearsal validates relocation to a path with spaces, direct entry,
selection, and failed-check refusal. The package gate runs the full shared suite,
and its `live` gate invokes only `dev build-check`. Development candidates
report Build `0` and are separate from the numbered registry.

The packaged development commands are part of the public executable:

```sh
bin/arbol-codex-driver dev probe
bin/arbol-codex-driver dev build-check
bin/arbol-codex-driver dev live-check
```

`dev probe` sends no inference request. Since ABR-64 it reads the installed
tool version and one native account read without a token refresh, on the
default profile, and reports booleans only. It starts no login, logout, thread,
hook or MCP server. Its earlier schema, device-login, disposable-home, history
and resume observations are dated historical evidence.

Both live commands use only the existing native `chatgpt` Subscription, refuse
unsigned or exhausted accounts before inference, and refresh usage before
every attempt. The build
check sends exactly one no-tools ready message. The extended live check includes
tools, a child and background work, continuity and stopping; run it only when
requested. Reports include attempted turns, observed starts, token usage and
usage changes, plus source/runtime/tool provenance, and are written under the
selected state directory's `research/`. Historical task scripts and evidence
remain dated; they do not run in the offline suite.

Package version and build number are separate. A source checkout reports build
`0`; a copied Build reads `build.json` beside its package. Build selection is the
job of the `arbol-builds` launcher. Package version `1.0.0` stays unchanged
across Builds until the owner changes it.

## Sylvan Stack 2

| Repository | Package | Version | Artifact corpus | Artifact repository |
|---|---|---|---|---|
| `arbol` | `@sylvan-stack/arbol` | 2.0.0 | `~/Artifacts/arbol` | `sylvan-stack/arbol-artifacts` |
| `arbol-root` | `@sylvan-stack/arbol-root` | 1.0.0 | `~/Artifacts/arbol-root` | `sylvan-stack/arbol-root-artifacts` |
| `arbol-trunk` | `@sylvan-stack/arbol-trunk` | 1.0.0 | `~/Artifacts/arbol-trunk` | `sylvan-stack/arbol-trunk-artifacts` |
| `arbol-claude-driver` | `@sylvan-stack/arbol-claude-driver` | 1.0.0 | `~/Artifacts/arbol-claude-driver` | `sylvan-stack/arbol-claude-driver-artifacts` |
| `arbol-codex-driver` | `@sylvan-stack/arbol-codex-driver` | 1.0.0 | `~/Artifacts/arbol-codex-driver` | `sylvan-stack/arbol-codex-driver-artifacts` |
| `arbol-browser` | `@sylvan-stack/arbol-browser` | 1.0.0 | `~/Artifacts/arbol-browser` | `sylvan-stack/arbol-browser-artifacts` |
| `mycel` | `@sylvan-stack/mycel` | 2.0.0 | `~/Artifacts/mycel` | `sylvan-stack/mycel-artifacts` |
| `arbol-pi-driver` | `@sylvan-stack/arbol-pi-driver` | 1.0.0 | `~/Artifacts/arbol-pi-driver` | `sylvan-stack/arbol-pi-driver-artifacts` |
| `workspace-ledger` | `workspace-ledger` (planned) | 1.0.0 | `~/Artifacts/sylvan-stack/repos/workspace-ledger` | `sylvan-stack/workspace-ledger-artifacts` |
