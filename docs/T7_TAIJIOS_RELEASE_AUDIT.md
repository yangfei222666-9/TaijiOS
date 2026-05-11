# T7 TaijiOS Release Audit

Created: 2026-05-10
Auditor machine: Win11
Auditor actor: Codex
Source disk: `G:\` (`T7`, Samsung PSSD T7, exFAT)
Source repo: `G:\TaijiOS-release`
Source remote: `https://github.com/yangfei222666-9/taiji.git`
Target repo considered: `C:\Users\A\TaijiOS`
Target remote: `https://github.com/yangfei222666-9/TaijiOS.git`

## Scope

This audit is read-only. No files were copied from T7 and no runtime code was migrated. The goal is to preserve useful project memory from `G:\TaijiOS-release` as reviewed artifact evidence before any future merge.

## Source State

`G:\TaijiOS-release` is not the same GitHub project as the current C-drive `TaijiOS` checkout.

- T7 branch: `main`
- T7 state: `main...origin/main [ahead 4]`
- T7 `HEAD`: `c7557f97636e08d22ceb3ea927d47e0e79af9205`
- T7 `origin/main`: `6648568b19b19222d1ccf58a558d3c357969350b`
- T7 tracked files: 313
- C-drive branch: `master`
- C-drive state before this audit: `master...origin/master [ahead 1]` plus uncommitted cross-machine handoff artifacts

The T7 repo has one tracked local modification:

- `aios/policy/hexagram_logger.py`

The T7 repo has six untracked files:

- `aios/arena/signal_bot.py`
- `aios/arena/signal_learn.py`
- `aios/voice/doubao_tts_v3.py`
- `docs/LAYERED_ARCHITECTURE.md`
- `EntroCamp学习笔记/reasoning-L3.md`
- `EntroCamp学习笔记/safety-L2.md`

## Ahead Commits

T7 is ahead of `origin/main` by four commits:

- `57d53b0` `feat: 补齐 policy/ 和 evolution_fusion，从 fallback 切换到真实计算`
- `013d153` `feat: 补齐感知层桥梁，Ising 脉搏引擎完整管线打通`
- `94c3cc4` `fix: 收尾修复 #19 #22 #29 #30`
- `c7557f9` `fix: task_queue_manager 和 evolution_fusion 添加 sys.path 设置`

Combined diff from `origin/main..HEAD`:

- 25 files changed
- 2791 insertions
- 33 deletions

Main additions:

- `aios/policy/*`
- `aios/agent_system/hexagram_lines.py`
- `aios/agent_system/evolution_fusion.py`
- `aios/agent_system/task_queue_manager.py`
- `aios/agent_system/tracer.py`
- `aios/event_bus.py`
- `tests/test_evolution_score.py`

## Useful Low-Risk Memory

### Provenance Fields

The local `hexagram_logger.py` modification adds provenance fields to `append_hexagram_state`:

- `caller`
- `agent_id`
- `trace_id`
- `trigger_event`

This is useful project memory and aligns with the cross-machine handoff model. If migrated, it should become a general event provenance convention, not a one-off `hexagram_logger` feature.

Recommended normalized provenance contract:

```json
{
  "caller": "module:function-or-file:line",
  "agent_id": "agent or machine identity",
  "trace_id": "cross-artifact correlation id",
  "trigger_event": "why this record was emitted",
  "source_repo": "repo name or URL",
  "source_ref": "branch/commit/local",
  "artifact_path": "path to evidence",
  "verified": false
}
```

### Layered Architecture Scan

`docs/LAYERED_ARCHITECTURE.md` is useful as design memory. It captures a layered view of perception, policy, scoring, execution, and EventBus boundaries. It should be treated as an audit snapshot from T7, not as guaranteed current architecture for C-drive `TaijiOS`.

Recommended use:

- Convert it into a reviewed architecture backlog.
- Cross-check each module path against current `C:\Users\A\TaijiOS`.
- Keep missing or conflicting modules as candidates, not facts.

## Do Not Migrate Directly

### `aios/arena/signal_bot.py`

Do not migrate into mainline without a separate safety patch.

Observed risks:

- Reads `G:\taijios_full_workspace\.env`.
- Writes to `G:\taijios_full_workspace\signal_arena`.
- Uses `AGENT_WORLD_API_KEY`.
- Calls real `POST /trade`.
- No default dry-run gate.

Minimum gate before any future migration:

- `DRY_RUN=true` by default.
- No hardcoded `G:\` paths.
- No trade execution without explicit human approval.
- All API keys loaded through the target project's secret manager.
- Test coverage for no-trade behavior.

### `aios/voice/doubao_tts_v3.py`

Do not migrate without fixing locking behavior.

Observed risk:

- `_speaking_lock` is acquired in `synthesize`.
- It is released on the exception path.
- No clear release was found on successful session completion.

This can make a second successful synthesis permanently skip with "正在播放中，跳过".

### `aios/event_bus.py`

Do not copy as a second event bus. The C-drive project already has `aios/core/event_bus.py`. Any migration must reconcile semantics with the existing event bus instead of creating parallel infrastructure.

### EntroCamp Notes

`EntroCamp学习笔记/*.md` can be reviewed as lesson candidates only. They should not become durable rules until a real failure, fix, verification result, and human review are attached.

## Verification Notes

Checks performed:

- Reviewed `git status`, remote, ahead commits, and diff stats for `G:\TaijiOS-release`.
- Reviewed the uncommitted diff in `aios/policy/hexagram_logger.py`.
- Reviewed untracked file names and selected contents without opening secret files.
- Confirmed `G:\taijios_full_workspace\.env` exists but did not read its contents.
- `ast.parse` passed for:
  - `aios/arena/signal_bot.py`
  - `aios/arena/signal_learn.py`
  - `aios/voice/doubao_tts_v3.py`
  - `aios/policy/hexagram_logger.py`
- Import smoke passed for:
  - `aios.event_bus`
  - `aios.agent_system.hexagram_lines`
  - `aios.agent_system.evolution_fusion` when `G:\TaijiOS-release\aios\agent_system` was manually inserted into `sys.path`
- `tests/test_evolution_score.py` import failed because it inserts `repo\agent_system` instead of `repo\aios\agent_system`.
- `git diff --check origin/main..HEAD` failed due to trailing whitespace in the ahead commits.

## Minimal Migration Decision

Only migrate project memory now:

- Keep this audit report.
- Preserve the provenance field contract as a candidate standard.
- Preserve the architecture scan as a candidate backlog input.
- Do not migrate runtime modules from T7 in this pass.

Future migration must happen as narrow patches with tests and a fresh handoff packet.
