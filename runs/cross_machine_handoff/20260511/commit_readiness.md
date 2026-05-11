# Commit Readiness Packet

Created: 2026-05-11T01:33:06+08:00

Last updated: 2026-05-11T18:18:43+08:00

Machine: win11

Actor: codex

Repo: TaijiOS

Ref: master local working tree

## Status

Ready for human review before staging. No commit, push, or PR has been created.

Latest verification:

- `python -m pytest tests\test_deepseek_iching_runner.py -q --tb=short` passed with 13 tests, including DeepSeek key whitespace handling and PowerShell helper regression coverage.
- `python -m pytest tests\test_gui_agent_events.py tests\test_gui_agent_poc.py tests\test_deepseek_iching_runner.py -q --tb=short` passed with 22 tests after adding GUI event/confirmation-log redaction coverage and DeepSeek output-dir collision coverage.
- `python -m pytest tests\test_core_smoke.py -q --tb=short` passed with 13 tests after adding coverage for repeated `worker.main(argv)` calls after `_SHUTDOWN=True` and for `health_check.main()` when `agents.json` is absent.
- `python -m pytest tests\test_browser_adapter.py tests\test_playwright_browser_adapter.py tests\test_browser_readonly_task.py tests\test_browser_readonly_validation.py tests\test_ops_check_validation.py -q --tb=short` passed with 32 tests after browser read-only allowlist hardening.
- `python aios\agent_system\health_check.py` now exits successfully in this checkout even though `aios/agent_system/agents.json` is absent; it prints the missing-data message instead of failing the CLI.
- `python -m worker --max-cycles 1 --interval 999 --dry-run --skip-learning --skip-jobs --data-dir data\worker_smoke` completed one cycle without sleeping after the shutdown-reset fix.
- `python examples\deepseek_iching_64.py` passed in dry-run mode with 64 completed hexagrams, 0 errors, 0 API calls, and a unique `runs/iching/deepseek_iching_64_<timestamp>_<microseconds>_<pid>_<nonce>/**` output directory.
- `python examples\validate_deepseek_iching_64.py` passed by resolving `runs/iching/latest_output_dir.txt` and checking the latest unique run artifacts.
- Latest dry-run `event_flow.jsonl` had 64 `hexagram.completed` events, 0 `deepseek.*` live request events, and 0 live-flag mismatches. Validator now rejects mixed dry-run/live event_flow artifacts.
- `python scripts\verify_project_health.py` passed without manual `TMP/TEMP` overrides with 101 tests, 102 import candidates, 136 Python files compiled, 26 tracked JSON/JSONL files parsed, 4 handoff files parsed, 174 files checked by secret-literal scan with 0 findings, GUI ops-check gate + validator green, DeepSeek I Ching dry-run + validator green, worker dry-run green, and 0 pyflakes findings.
- `python scripts\verify_project_health.py --skip-tests` passed with 13 checks and 0 failures, including the new secret-literal scan.
- `python -m pytest tests\test_browser_adapter.py tests\test_browser_readonly_task.py tests\test_browser_readonly_validation.py tests\test_ops_check_validation.py tests\test_playwright_browser_adapter.py tests\test_policy_matrix.py tests\test_shadow_mode_browser_poc.py -q --tb=short` passed with 36 tests after fake secret fixtures were changed to runtime-composed strings.
- Strict changed-file secret scan returned no findings after removing continuous fake secret literals from GUI/browser fixtures.
- The focused GUI gate tests are covered by the 97-test full pytest run; the earlier 13-test focused gate subset also passed.
- GUI agent events and JSONL confirmation logs now redact secret-like instruction text before persistence. The first test version intentionally tripped the secret literal scan; the fixture was corrected to compose the fake token at runtime, and the full verifier returned to 0 findings.
- Group 1 review fixed two runtime edge cases: worker no longer inherits a stale `_SHUTDOWN=True` across embedded invocations, and health_check no longer treats missing optional `agents.json` data as a failing CLI exit.
- Group 2 review hardened browser read-only controls: explicit empty offline allowlists now block instead of inferring registered hosts, Playwright route guard aborts secret-like subrequest URLs, and browser artifact validation rejects summary/event_flow URLs outside `allowed_hosts`.
- `python -m aios.gui_agent.ops_check_gate` and `python examples\validate_gui_agent_ops_check.py` passed with default ignored `runs/ops_check/**` outputs.
- `python examples\browser_readonly_task.py`, `python examples\validate_browser_readonly_task.py`, and `python examples\validate_shadow_mode_browser_poc.py` passed with default ignored `runs/ops_check/**` outputs.
- `git check-ignore -v runs\iching\latest_output_dir.txt` confirmed generated I Ching runtime artifacts and the latest-run pointer are ignored by `.gitignore`.
- PowerShell parser validation passed for `scripts\run_deepseek_iching_live.ps1` and `scripts\save_deepseek_key_dpapi.ps1`; no hardcoded secret literal was found by the verifier secret scan.
- DeepSeek live helper now fails closed on runner or validator failure via `Invoke-NativeChecked`; the DPAPI key store writes `data/secrets/deepseek_api_key.dpapi` with `-NoNewline`, and the live helper trims encrypted text before decrypting it.
- `python examples\deepseek_iching_64.py --live` without `DEEPSEEK_API_KEY` returned `exit_code=2` and did not perform a live API call.
- `git add -n` passed for all four proposed staging groups. Dry-run coverage: group 1 = 56 files, group 2 = 46 files, group 3 = 6 files, group 4 = 8 files; union = 116 files, current changed files = 116, missing = 0, extra = 0.
- Final pre-staging dry-run recheck passed: group 1 = 56 files, group 2 = 46 files, group 3 = 6 files, group 4 = 8 files; union = 116 files, current changed files = 116, missing = 0, extra = 0, cached = 0.
- CI-pattern secret scan over `.github`, source packages, examples, scripts, and tests returned no matches.
- `git diff --check` passed with Windows CRLF normalization warnings only.

## Recommended Commit Strategy

The safest commit sequence is two commits:

1. Commit code/runtime work together by staging groups 1, 2, and 4 in the same commit.
2. Commit audit and handoff evidence separately by staging group 3.

Reason: `.github/workflows/ci.yml` and `scripts/verify_project_health.py` now run GUI ops-checks and DeepSeek I Ching dry-run/validation. If group 1 is committed alone, CI can reference files from groups 2 and 4 that are not present yet. A four-commit split is still possible, but only with partial staging of CI/verifier changes or by landing groups 2 and 4 no later than the commit that introduces the final verifier.

## Suggested Commit Groups

### 1. Stabilize runtime imports, entrypoints, CI, and verifier

Purpose: make the existing project importable, compilable, locally verifiable, and CI-verifiable.

Include:

- `.github/workflows/ci.yml`
- `.gitignore`
- `pyproject.toml`
- `scripts/verify_project_health.py`
- Existing tracked modules under `aios/agent_system`, `aios/core`, `aios/gateway`, `coherent_engine`, `github_learning`, `self_improving_loop`, and `worker`
- `examples/quickstart_minimal.py`
- `examples/success_lift_test.py`
- `examples/success_lift_v2.py`
- `tests/test_core_smoke.py`

Suggested message:

`Stabilize runtime imports and add project verifier`

Staging command:

```powershell
git add -- .github\workflows\ci.yml .gitignore pyproject.toml scripts\verify_project_health.py aios\agent_system aios\core aios\gateway coherent_engine github_learning self_improving_loop worker examples\quickstart_minimal.py examples\success_lift_test.py examples\success_lift_v2.py tests\test_core_smoke.py
```

### 2. Add GUI agent shadow and browser read-only POC

Purpose: add the UI-TARS-style GUI agent POC with shadow-mode policy, confirmation flow, read-only browser tasks, validation, and tests.

Include:

- `aios/gui_agent/**`
- `docs/UI_TARS_AGENT_POC.md`
- `docs/UI_TARS_POLICY_MATRIX.md`
- `examples/browser_readonly_task.py`
- `examples/gui_agent_shadow_demo.py`
- `examples/shadow_mode_browser_poc.py`
- `examples/validate_browser_readonly_task.py`
- `examples/validate_gui_agent_ops_check.py`
- `examples/validate_shadow_mode_browser_poc.py`
- `tests/test_browser_adapter.py`
- `tests/test_browser_readonly_gate.py`
- `tests/test_browser_readonly_task.py`
- `tests/test_browser_readonly_validation.py`
- `tests/test_event_flow_replay.py`
- `tests/test_gui_agent_events.py`
- `tests/test_gui_agent_poc.py`
- `tests/test_ops_check_gate.py`
- `tests/test_ops_check_validation.py`
- `tests/test_playwright_browser_adapter.py`
- `tests/test_poc_gate.py`
- `tests/test_poc_validation.py`
- `tests/test_policy_manifest.py`
- `tests/test_policy_matrix.py`
- `tests/test_shadow_mode_browser_poc.py`
- `tests/test_windows_operator.py`

Suggested message:

`Add GUI agent shadow-mode POC`

Staging command:

```powershell
git add -- aios\gui_agent docs\UI_TARS_AGENT_POC.md docs\UI_TARS_POLICY_MATRIX.md examples\browser_readonly_task.py examples\gui_agent_shadow_demo.py examples\shadow_mode_browser_poc.py examples\validate_browser_readonly_task.py examples\validate_gui_agent_ops_check.py examples\validate_shadow_mode_browser_poc.py tests\test_browser_adapter.py tests\test_browser_readonly_gate.py tests\test_browser_readonly_task.py tests\test_browser_readonly_validation.py tests\test_event_flow_replay.py tests\test_gui_agent_events.py tests\test_gui_agent_poc.py tests\test_ops_check_gate.py tests\test_ops_check_validation.py tests\test_playwright_browser_adapter.py tests\test_poc_gate.py tests\test_poc_validation.py tests\test_policy_manifest.py tests\test_policy_matrix.py tests\test_shadow_mode_browser_poc.py tests\test_windows_operator.py
```

### 3. Add audit and cross-machine handoff evidence

Purpose: preserve the T7 audit and this Win11-to-Mac handoff evidence.

Include:

- `docs/T7_TAIJIOS_RELEASE_AUDIT.md`
- `runs/cross_machine_handoff/20260510/context_packet_t7_release_audit.md`
- `runs/cross_machine_handoff/20260511/context_packet_project_bugfix.md`
- `runs/cross_machine_handoff/20260511/event_flow.jsonl`
- `runs/cross_machine_handoff/20260511/verification_summary.json`
- `runs/cross_machine_handoff/20260511/commit_readiness.md`

Suggested message:

`Add cross-machine handoff evidence`

Staging command:

```powershell
git add -- docs\T7_TAIJIOS_RELEASE_AUDIT.md runs\cross_machine_handoff\20260510\context_packet_t7_release_audit.md runs\cross_machine_handoff\20260511\context_packet_project_bugfix.md runs\cross_machine_handoff\20260511\event_flow.jsonl runs\cross_machine_handoff\20260511\verification_summary.json runs\cross_machine_handoff\20260511\commit_readiness.md
```

### 4. Add DeepSeek I Ching batch runner

Purpose: add the DeepSeek-backed 64-hexagram batch runner, dry-run default, validator, documentation, and tests.

Include:

- `aios/iching/**`
- `docs/DEEPSEEK_ICHING_64.md`
- `examples/deepseek_iching_64.py`
- `examples/validate_deepseek_iching_64.py`
- `scripts/run_deepseek_iching_live.ps1`
- `scripts/save_deepseek_key_dpapi.ps1`
- `tests/test_deepseek_iching_runner.py`

Suggested message:

`Add DeepSeek I Ching batch runner`

Staging command:

```powershell
git add -- aios\iching docs\DEEPSEEK_ICHING_64.md examples\deepseek_iching_64.py examples\validate_deepseek_iching_64.py scripts\run_deepseek_iching_live.ps1 scripts\save_deepseek_key_dpapi.ps1 tests\test_deepseek_iching_runner.py
```

Note: `scripts/verify_project_health.py` now includes this runner and validator in the project verifier. If committing in strictly green steps, stage the DeepSeek group before or together with the verifier file, or use partial staging for verifier changes.

## Do Not Stage

- `data/**` runtime output.
- `data/secrets/**` DPAPI-protected local key material.
- `runs/ops_check/**` local ops-check runtime artifacts unless explicitly approved as evidence.
- `runs/iching/**` local DeepSeek/I Ching runtime artifacts unless explicitly approved as evidence.
- Any `.env`, `auth.json`, `api_keys.json`, key, token, database, cache, or binary runtime file.

## Reviewer Notes

- The working tree is intentionally large. Review by commit group, not as one undifferentiated patch.
- `git add -n` now works in this Win11 workspace and confirms all four staging commands resolve to the intended files. The previous index-lock dry-run blocker is no longer current.
- The GUI agent POC is validated with dry-run/offline/fake backends only. Real Win32 input and live browser execution remain unverified.
- GUI EventBus payloads and JSONL confirmation records are redacted before persistence, but this pass still did not exercise real desktop input.
- GUI ops-check validation now replays generated event_flow policy decisions against `policy_matrix.json`; stale local `runs/ops_check/**` artifacts can fail validation until `python -m aios.gui_agent.ops_check_gate` regenerates them.
- DeepSeek I Ching live API success remains unverified in this pass; the verified live failure path is fail-closed when `DEEPSEEK_API_KEY` is absent, and the verified normal path is dry-run/resume with cached artifacts and `api_call_count=0`.
- A background `python examples\deepseek_iching_64.py --live --fresh` process was observed writing to the older date-only default directory. New code avoids that collision for future runs by using unique timestamp-microseconds-pid-nonce default output directories, but that already-running process was not stopped.
- The DeepSeek PowerShell helper scripts use DPAPI-protected local storage under ignored `data/secrets/**`, trim DPAPI file text before decryption, store without trailing newline, check native Python exit codes, and set `DEEPSEEK_API_KEY` only for the child live-run process.
- `aios/agent_system/agents.json` is absent in this checkout, so real agent health scoring remains unverified.
- Default GUI ops-check gates write local runtime artifacts under ignored `runs/ops_check/**`; these were not staged.
