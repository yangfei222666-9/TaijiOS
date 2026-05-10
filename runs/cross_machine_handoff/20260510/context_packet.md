# Context Packet: Cross-Machine Handoff Protocol Bootstrap

Created: 2026-05-10
Producer machine: Win11
Producer actor: Codex
Repo: TaijiOS
Local path: `C:\Users\A\TaijiOS`
Git state before work: `master...origin/master [ahead 1]`, clean worktree

## Trigger

The operator tightened the definition of Mac/Win11 co-evolution: both machines must collaborate through verifiable artifacts, not chat state. The requested minimum loop is:

- `docs/CROSS_MACHINE_OPERATING_PROTOCOL.md`
- `runs/cross_machine_handoff/YYYYMMDD/event_flow.jsonl`
- `runs/cross_machine_handoff/YYYYMMDD/context_packet.md`
- `runs/cross_machine_handoff/YYYYMMDD/verification_summary.json`

The operator then clarified the project-memory boundary: machines may share project memory through artifacts, but not through automatic internal memory sharing. Secrets, unverified status, and unsupported "self-evolution complete" claims are outside the shared-memory boundary.

## Decision

This bootstrap is placed in `TaijiOS`, not `hermes-agent`, because `TaijiOS` is the local self-evolution project and `hermes-agent` is an upstream dependency-style repository.

## Authoritative Artifacts

- `docs/CROSS_MACHINE_OPERATING_PROTOCOL.md`
- `runs/cross_machine_handoff/20260510/event_flow.jsonl`
- `runs/cross_machine_handoff/20260510/context_packet.md`
- `runs/cross_machine_handoff/20260510/verification_summary.json`
- `.gitignore` exception for tracked cross-machine `event_flow.jsonl`

## What Changed

- Added a cross-machine operating protocol.
- Added the first dated handoff packet directory.
- Added an append-only event flow for this bootstrap.
- Added a verification summary placeholder to be filled by local checks.
- Adjusted `.gitignore` so handoff `event_flow.jsonl` files can be tracked despite the global `*.jsonl` ignore.
- Added explicit project-memory boundaries: artifact-only sharing, no secrets, no unverified state as memory, no self-evolution claim without promoted behavior, and reviewed lessons only.

## Verification Plan

Run local checks after file creation:

- Confirm all required files exist.
- Parse `event_flow.jsonl` one line at a time as JSON.
- Parse `verification_summary.json` as JSON.
- Check git status for the resulting artifact set.

## Next Machine Action

Mac should perform read-only review:

1. Read this packet.
2. Parse the event flow and verification summary.
3. Check the four artifact classes: protocol doc, context packet, event flow, verification summary.
4. Confirm that JSONL parses, JSON parses, boundaries are not violated, and the event flow can be tracked by git.
5. Either accept the handoff or write `handoff.rejected` with concrete missing artifacts.

## Must Not Be Assumed

- No tests of TaijiOS runtime behavior have been run for this document-only change.
- No GitHub push or PR has happened yet.
- Telegram liveness is not considered completion evidence.
- This is a protocol bootstrap, not proof that rule promotion already affects system behavior.
- This packet shares project memory only. It does not claim access to any machine's internal model memory.
