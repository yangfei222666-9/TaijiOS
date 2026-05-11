# Project Bugfix Context Packet

## Scope

Repository: TaijiOS

Machine: win11

Actor: codex

Local ref: master local working tree

Request: broad project optimization and bug hunt.

## Problems Found

- `aios.core.event_bus` could not import because `aios.storage.event_store_adapter` is absent in this checkout.
- `aios.agent_system.task_executor` had a BOM plus damaged comments/docstrings that swallowed executable assignments and broke compilation.
- `aios.agent_system` package import depended on legacy modules that are absent.
- CI targeted `coherent_engine/tests/`, which does not exist in this repo.
- `aios.core.reactor` depended on missing `core.decision_log` and set `PYTHON` to the literal string `sys.executable`.
- `coherent_engine.core.orchestrator` depended on absent optional module classes.
- Full package import scan later found three more missing legacy adapters: `agent_status`, `core.status_adapter`, and `aios.agent_system.config_center`.
- Gateway CLI ignored README-documented `--port` and treated `--help` as a server start.
- Quickstart wrote runtime evidence into tracked sample JSON files and printed a Unicode title that rendered poorly in the Windows shell.
- Static analysis found runtime `NameError` risks: swallowed `skill_id` assignment, missing `_tail_lines`, and undefined `THRESHOLD_CONFIG_FILE`.
- `github_learning.manifest` defined `revoke()` twice.
- `task_router` repeated the Chinese keyword `修复`, so one route mapping silently shadowed the other.
- GUI agent terminal actions were inconsistent: `Action.is_terminal` included `error_env/max_loop`, but policy and run-loop handling did not.
- GUI shadow demo wrote runtime confirmation logs under `examples/quickstart_output`.
- Worker `--max-cycles 1` completed a cycle and then slept the full interval before exiting.
- Worker `--dry-run` still allowed maintenance refreshes after a cycle, which could write runtime snapshots.
- Shadow-mode browser POC defaulted to `runs/ops_check/...`, so running the demo produced untracked repo artifacts.
- Shadow-mode browser POC validator still defaulted to the old `runs/ops_check/...` output path after the generator moved.
- GUI action parser only split multiple actions on blank lines, so adjacent UI-TARS action lines could be dropped.
- Shadow-mode POC gate defaulted to the old `runs/ops_check/...` output path.
- There was no one-command verifier to reproduce the import/compile/entrypoint/handoff checks locally or in CI.
- The static-analysis check was too noisy for CI because low-risk pyflakes cleanup items obscured high-signal failures.
- `.gitignore` allowed future `runs/ops_check` demo artifacts to surface in `git status`.
- Browser read-only task example also defaulted to `runs/ops_check/...`.

## Changes Made

- Added local JSONL fallback storage for `EventBus`.
- Repaired `task_executor` encoding/comment damage and restored memory retrieval constants.
- Made `aios.agent_system` importable without legacy dependencies while keeping `AgentSystem()` failure explicit.
- Updated CI to install dev dependencies and run `tests/`.
- Added smoke tests for importability and fallback behavior.
- Added fallback `decision_log` functions and fixed reactor Python executable handling.
- Added optional `BaseModule` fallback for coherent orchestrator imports.
- Added fallback status/config adapters for `health_check`, `task_router`, and `unified_registry`.
- Made `health_check` fail gracefully when local agent data is absent instead of raising a traceback.
- Added Gateway CLI argument parsing for `--host`, `--port`, and `--log-level`.
- Changed quickstart runtime output to `data/quickstart_output` by default and kept `TAIJIOS_QUICKSTART_OUTPUT_DIR` override support.
- Restored `skill_id` assignment, added `_tail_lines`, and made adaptive threshold config use its instance `config_file`.
- Removed duplicate `manifest.revoke()` and de-duplicated `task_router` keyword routing for `修复`.
- Made GUI terminal actions policy-allowed and handled through one terminal branch; added `user_stop` terminal support.
- Added confirmation-store export and validated confirmation events.
- Moved GUI shadow demo output to ignored `data/gui_agent_shadow_demo`.
- Added worker `--data-dir` / `TAIJIOS_WORKER_DATA_DIR`, defaulting runtime status to ignored `data/worker`.
- Made dry-run skip maintenance refreshes and made `--max-cycles` stop before sleeping.
- Moved shadow-mode browser POC demo output to ignored `data/shadow_mode_browser_poc`.
- Updated shadow-mode browser POC validator default path to `data/shadow_mode_browser_poc`.
- Added action-call splitting that handles adjacent multi-line UI-TARS actions and preserved quoted commas.
- Updated shadow-mode POC gate default output path to `data/shadow_mode_browser_poc`.
- Added `scripts/verify_project_health.py` to run tests, import scan, py_compile, tracked JSON/JSONL parse, handoff parse, high-signal pyflakes scan, and key entrypoint smoke checks.
- Added `pyflakes` to dev dependencies and wired the verifier into CI with `python scripts/verify_project_health.py --skip-tests`.
- Made verifier subprocesses inherit a repo-root `PYTHONPATH` and suppress low-risk pyflakes details unless high-signal findings are present.
- Ignored `runs/ops_check/` while keeping `runs/cross_machine_handoff/**/event_flow.jsonl` trackable.
- Removed remaining pyflakes findings across core, gateway, coherent engine, GitHub learning, self-improving loop, and example modules.
- Re-verified that shadow-mode POC gate writes to ignored `data/shadow_mode_browser_poc`.
- Moved browser read-only task example output to ignored `data/browser_readonly_task`.
- Added browser read-only artifact validator and CLI.
- Added `commit_readiness.md` with suggested commit groups and do-not-stage guidance.

## Verification

- `python scripts\verify_project_health.py` passed with `checks_run=10` and `checks_failed=0`.
- Verifier full path included `pytest`: 63 tests passed.
- Full import scan over `aios`, `coherent_engine`, `github_learning`, `self_improving_loop`, and `worker` passed with 94 candidates and 0 failures.
- Full local Python compile passed with 119 files and 0 errors.
- Tracked JSON/JSONL parse passed with 26 files and 0 failures.
- Handoff artifact parse passed with 4 files and 0 failures.
- pyflakes scan reported 0 findings.
- Entry smoke checks passed: `python -m aios.gateway --help`, `python examples\quickstart_minimal.py`, `python -m aios.gui_agent.poc_gate`, and worker dry-run. POC gate output is under ignored `data/shadow_mode_browser_poc`.
- Browser read-only task tests passed with 4 tests, including host allowlist and secret URL blocking.
- Browser read-only validation CLI passed against ignored `data/browser_readonly_task` artifacts.
- `python scripts\verify_project_health.py --skip-tests` passed with `checks_run=9` and `checks_failed=0`; this is the CI path added in this pass.
- `git diff --check` passed; only CRLF normalization warnings were reported by Git on Windows.
- `python aios\agent_system\health_check.py` now reports missing `agents.json` and exits nonzero without traceback.

## Remaining Risk

- This is a compatibility and smoke-level stabilization pass, not a full behavioral test of every workflow.
- Runtime data such as `aios/agent_system/agents.json` is absent in the current C-drive checkout, so health scoring cannot be validated with real agent data.
- Untracked GUI agent files/tests exist in the working tree and were included in the latest local pytest/import/compile checks. Third-round changes touched this GUI agent POC to fix terminal action, confirmation export, and demo output behavior.
- Existing untracked `runs/ops_check/shadow_mode_browser_poc_20260511` artifacts were not deleted; they may be prior evidence and need human review before cleanup, but future `runs/ops_check/` artifacts are now ignored.
- No commit, push, or PR has been created in this pass.
