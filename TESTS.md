# Tests: arbol-codex-driver

Both tiers have uncommented source. Only the top-tier cases below may be selected during implementation. They may be selected when useful during implementation; running tests after every change is not required. Writing or running mid-tier tests requires a separate testing task explicitly requested by the owner. Do not write or restore low-tier tests.

[Mid-tier descriptions and justifications](MID_TIER.md) · [Complete inventory and tier justifications](docs/test-inventory.md) · [Machine-readable inventory](test-tiers.json)

Reviewed revision: `0c596c5960c34039bd48d05df9b66b4ea9f31680` under SYL-327 (29 October 2026). No tests were run.

## Selection and limits

2 top-tier inventory entries and 49 mid-tier entries are available after the higher-bar review. 88 low-tier entries were removed under SYL-327. Definitions, scenarios, programs and entry points overlap; this is not a runtime suite count. Top-tier bodies are unchanged. Retained mid-tier sources remain uncommented.

## Active top tier

| Exact selector or program | Why this case earns a place |
| --- | --- |
| [`test_top_app_server.AppServerTests.test_timeout_and_cancellation_include_blocked_stdin_drain`](tests/top/test_top_app_server.py#L15) | Blocks the app-server stdin drain before the reply wait. Exercises timeout and explicit cancellation at that earlier boundary, where a timeout wrapped only around response handling would fail. |
| [`test_top_process_groups.ForcedProcessGroupTests.test_immediate_kill_refuses_reused_or_wrong_group_leaders`](tests/top/test_top_process_groups.py#L16) | Feeds changed process start time and changed process group into the immediate-kill path and asserts that no group signal is sent. Protects unrelated processes from cleanup of a stale owner. |

## Layout and shared support

Case bodies are separated into [`tests/top/`](tests/top/) and [`tests/mid/`](tests/mid/). The former mixed test modules retain shared fixture classes, helper functions and imports at their established paths, with no inventoried test methods. This preserves existing subprocess paths, patch targets and fixture imports without copying helpers into both tiers. Compatibility entries preserve original package and resource paths while loading the mid-tier implementation. Product-side test APIs load it only when invoked and refuse if the test source is absent.

## Running a selected top-tier case

Select an exact method when it resolves a concrete uncertainty; no run is required after an edit. The new module names begin with test_top_ so they cannot shadow the shared fixture modules. Do not run whole folders or discovery as a substitute. Original prerequisites, skips and environment limitations still apply. A focused result is not full qualification.

From the repository root, using the prepared repository interpreter:

```sh
PYTHONPATH=src:tests:tests/top python -m unittest test_top_app_server.AppServerTests.test_timeout_and_cancellation_include_blocked_stdin_drain
```

## Mid-tier execution

[MID_TIER.md](MID_TIER.md) lists the descriptions, tier reasons and review status. The source is now uncommented and stays that way. Writing or running it still requires a separately requested testing task. Do not run tests automatically after edits or merges. Inspect prerequisites and indirect calls before invoking a program or qualification entry point. A focused result is not full qualification.

For a Python method, use the same fixture setup as the top tier, put the mid folder on PYTHONPATH, and select `test_mid_<module>.Class.test_method`. Mycel's fixture-aware runner accepts `--tests tests/mid --select test_mid_<module>.Class.test_method`; store cases require explicit disposable-store settings. Archived scenarios and programs retain their original compatibility entry paths.

Restoration under SYL-326 used static checks only. No tests, Builds, provider calls, Origin migrations or corpus ingest were performed. Original prerequisites and environment limits still apply.

## Qualification after SYL-327

The historical packaged unit gate refuses after this substantial pruning. A separately requested qualification task must review the reduced selection before restoring that gate. Individual top and mid selections remain governed by the policy above; their results cannot stand in for the former complete Build qualification.
