# Cross-Machine Operating Protocol

Status: active draft
Owner: TaijiOS operators
Applies to: Mac Codex, Win11 Codex, human reviewer
Created: 2026-05-10

## Purpose

Mac and Win11 do not co-evolve by exchanging chat state. They co-evolve by sharing verifiable artifacts. A handoff is valid only when it includes:

- `context_packet.md`: what happened, what changed, what the next machine must know.
- `event_flow.jsonl`: append-only event stream for the work.
- `verification_summary.json`: machine-readable verification result.
- GitHub state: commit, branch, PR, tag, or explicit "not yet pushed" state.

Any claim without an artifact is treated as unverified.

## Roles

Mac Codex is the COO and verifier. It owns audit, Telegram-facing status, quantitative gates, release/demo/portfolio packaging, and read-only review after Win11 implementation.

Win11 is the implementation workstation. It owns reimplementation, larger code edits, local long-running tasks, multi-repo cleanup, and pre-publication technical review.

The human reviewer owns rule promotion, release approval, and any decision that changes durable system policy.

## Source Of Truth

Use this precedence order:

1. GitHub commits, branches, pull requests, tags, and checks.
2. `runs/**/event_flow.jsonl`.
3. `runs/**/context_packet.md`.
4. `runs/**/verification_summary.json`.
5. Local artifacts referenced by the packet.
6. iCloud, Telegram, screenshots, and chat logs.

Telegram "alive" messages are liveness signals only. They are not evidence that work completed.

## Project Memory Boundaries

Cross-machine memory means project artifacts that another machine can read, verify, and absorb. It does not mean automatic sharing of internal model memory, chat impressions, hidden state, or unstated assumptions.

The shared memory boundary is strict:

- Do not share secrets, tokens, private keys, credential files, or raw environment values. Refer to secret names only.
- Do not promote unverified status into memory. If a state is not checked, label it as unverified.
- Do not record "self-evolution completed" unless a verified rule promotion or behavior change exists.
- Do not treat Win11 or Mac chat conclusions as durable memory until they are written as artifacts and reviewed.
- Do not use iCloud, Telegram, screenshots, or pasted chat as final source of truth.
- Do not add lessons from speculation. Lessons must come from real failures, repairs, or repeated operating evidence.

After Mac read-only review passes, GitHub becomes the long-term source of truth for the shared memory. Before that, local handoff artifacts remain `partial`.

## Handoff Directory

Each handoff uses:

```text
runs/cross_machine_handoff/YYYYMMDD/
  event_flow.jsonl
  context_packet.md
  verification_summary.json
```

If there are multiple handoffs on the same day, append to `event_flow.jsonl` and add clearly named packet files such as `context_packet_002.md`; keep `context_packet.md` as the latest packet for that date.

## Event Flow Schema

Each line in `event_flow.jsonl` is a JSON object:

```json
{
  "ts": "2026-05-10T15:30:00Z",
  "machine": "win11",
  "actor": "codex",
  "event": "implementation.completed",
  "repo": "TaijiOS",
  "ref": "branch-or-commit-or-local",
  "artifacts": ["path/to/artifact"],
  "summary": "short factual statement",
  "verified": false
}
```

Required fields: `ts`, `machine`, `actor`, `event`, `repo`, `summary`, `verified`.

Recommended event names:

- `problem.detected`
- `context_packet.created`
- `implementation.started`
- `implementation.completed`
- `verification.started`
- `verification.passed`
- `verification.failed`
- `handoff.accepted`
- `handoff.rejected`
- `rule.candidate.created`
- `rule.promoted`
- `rule.demoted`
- `rule.archived`

## Context Packet

Every packet must answer:

- What problem or task triggered this handoff?
- Which machine produced the packet?
- Which repo, branch, commit, and local paths are relevant?
- What artifacts are authoritative?
- What changed since the previous packet?
- What verification was run, with exact commands or explicit "not run" reasons?
- What is the next machine allowed to do?
- What must not be assumed?

The next machine must read the packet and verify artifacts before continuing.

## Verification Summary Schema

`verification_summary.json` uses this shape:

```json
{
  "schema_version": 1,
  "created_at": "2026-05-10T15:30:00Z",
  "machine": "win11",
  "repo": "TaijiOS",
  "git_ref": "local-or-commit",
  "status": "pass",
  "checks": [
    {
      "name": "jsonl_parse",
      "command": "exact command",
      "status": "pass",
      "evidence": "short factual result"
    }
  ],
  "unverified": [
    "Anything not actually verified"
  ],
  "next_required_action": "Mac read-only review"
}
```

Allowed `status` values: `pass`, `fail`, `partial`, `not_run`.

## Memory And Lessons Queue

Only record lessons that come from real failures, repairs, or repeated operating evidence. Do not record ideas, wishes, slogans, or speculative rules.

Only reviewed lessons can enter long-term rules. A Win11 conclusion is input evidence, not durable memory, until Mac verifies the artifact trail.

A lesson candidate must include:

- Triggering failure or concrete friction.
- Artifact path.
- Fix or mitigation.
- Verification result.
- Proposed rule text.
- Owner and review status.

## Rule Promotion Gate

A rule can enter durable system behavior only when all gates pass:

- `hit_count` meets the configured threshold.
- `cooldown` has elapsed since the last related change.
- `provider_taint=false`.
- `human_review=true`.
- At least one relevant test or verifier check passed.
- Demotion/archive criteria are defined.

Rules that fail verification stay as candidates. Rules that stop helping are demoted or archived with evidence.

## Standard Flow

1. Mac detects a problem and creates a context packet.
2. Win11 verifies the packet and implements or repairs.
3. Win11 writes patch, `event_flow.jsonl`, and `verification_summary.json`.
4. Mac performs read-only review against artifacts.
5. Only after verification passes can the change enter GitHub, demo, portfolio, or automation mainline.

## Invalid Handoffs

A handoff is invalid when:

- It only says "done" in chat.
- It has no event flow.
- It has no verification summary.
- It references stale or missing artifacts.
- It claims system learning without a promoted rule or behavior change.
- It treats liveness as completion.

## Minimum Acceptance Checklist

- The packet exists.
- The event flow exists and parses as JSONL.
- The verification summary exists and parses as JSON.
- Git status and relevant refs are recorded.
- Unverified items are explicit.
- The next machine has a concrete action.
