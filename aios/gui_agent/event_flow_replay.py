"""Replay GUI agent event flows against the policy matrix manifest."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from .redaction import contains_secret


@dataclass
class EventFlowReplayResult:
    """Result of replaying event flows against the policy matrix."""

    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checked_files: list[str] = field(default_factory=list)
    replayed_policy_events: int = 0

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "errors": self.errors,
            "warnings": self.warnings,
            "checked_files": self.checked_files,
            "replayed_policy_events": self.replayed_policy_events,
        }


def replay_event_flows(
    event_flow_paths: Sequence[str | Path],
    policy_manifest_path: str | Path,
) -> EventFlowReplayResult:
    """Replay event flows and verify policy decisions match the manifest."""
    errors: list[str] = []
    warnings: list[str] = []
    checked_files = [str(policy_manifest_path)]
    replayed_policy_events = 0

    manifest_path = Path(policy_manifest_path)
    manifest = _load_json(manifest_path, errors, "policy manifest")
    rows = manifest.get("rules") or []
    if not isinstance(rows, list):
        errors.append("policy manifest rules must be a list")
        rows = []

    all_events: list[dict] = []
    for raw_path in event_flow_paths:
        path = Path(raw_path)
        checked_files.append(str(path))
        events = _load_jsonl(path, errors, f"event flow {path.name}")
        all_events.extend(events)
        replayed_policy_events += _replay_one_flow(path, events, rows, errors, warnings)

    if replayed_policy_events == 0:
        errors.append("no replayable policy decisions found in event flows")

    if contains_secret({"manifest": manifest, "events": all_events}):
        errors.append("secret-like value found during event flow replay")

    return EventFlowReplayResult(
        ok=not errors,
        errors=errors,
        warnings=warnings,
        checked_files=checked_files,
        replayed_policy_events=replayed_policy_events,
    )


def _load_json(path: Path, errors: list[str], label: str) -> dict:
    if not path.exists():
        errors.append(f"missing artifact: {path.name}")
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        errors.append(f"{label} is not valid JSON: {exc}")
        return {}


def _load_jsonl(path: Path, errors: list[str], label: str) -> list[dict]:
    if not path.exists():
        errors.append(f"missing artifact: {path.name}")
        return []

    loaded: list[dict] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            loaded.append(json.loads(line))
        except json.JSONDecodeError as exc:
            errors.append(f"{label} line {line_number} is not valid JSON: {exc}")
    return loaded


def _replay_one_flow(
    path: Path,
    events: list[dict],
    rows: list[dict],
    errors: list[str],
    warnings: list[str],
) -> int:
    allowed_policy: dict[tuple[str, str, str], int] = {}
    policy_events = 0

    for index, event in enumerate(events, 1):
        event_type = event.get("type")
        payload = event.get("payload") or {}
        label = f"{path.name}:{index}:{event_type}"

        if _is_policy_event(event_type):
            policy_events += 1
            _replay_policy_event(
                label,
                payload,
                rows,
                allowed_policy,
                index,
                errors,
            )

        if event_type in {"browser.open.requested", "browser_readonly_task.open.requested"}:
            _require_prior_policy(
                label,
                allowed_policy,
                "browser_readonly",
                "navigate",
                _target(payload),
                errors,
            )
        elif event_type in {"browser.read.completed", "browser_readonly_task.read.completed"}:
            _require_prior_policy(
                label,
                allowed_policy,
                "browser_readonly",
                "read_current_page",
                _target(payload),
                errors,
            )
            if payload.get("side_effect") is not False:
                errors.append(f"{label} reported side_effect")
        elif event_type == "browser_readonly_task.open.completed":
            if payload.get("side_effect") is not False:
                errors.append(f"{label} reported side_effect")
        elif event_type == "gui_agent.action_executed":
            errors.append(f"{label} indicates live GUI action execution")

        if event_type == "gui_shadow.policy_decision" and payload.get("executed") is not False:
            errors.append(f"{label} did not remain in shadow mode")

    if events and policy_events == 0:
        warnings.append(f"{path.name} has no policy decision events")
    return policy_events


def _replay_policy_event(
    label: str,
    payload: dict,
    rows: list[dict],
    allowed_policy: dict[tuple[str, str, str], int],
    index: int,
    errors: list[str],
) -> None:
    action_type = payload.get("action_type")
    surface = _surface(payload, label)
    if not action_type:
        errors.append(f"{label} missing action_type")
        return

    row = _find_policy_row(rows, action_type, surface)
    if row is None:
        errors.append(f"{label} has no policy row for {action_type!r} on {surface!r}")
        return

    effect = row.get("effect")
    expected_allowed = effect in {"allow", "shadow"}
    expected_confirmation = bool(row.get("requires_confirmation")) or effect == "shadow"

    if payload.get("allowed") is not expected_allowed:
        errors.append(
            f"{label} allowed expected {expected_allowed!r}, "
            f"got {payload.get('allowed')!r}"
        )
    if payload.get("requires_confirmation") is not expected_confirmation:
        errors.append(
            f"{label} requires_confirmation expected {expected_confirmation!r}, "
            f"got {payload.get('requires_confirmation')!r}"
        )

    emitted_effect = payload.get("effect")
    if emitted_effect != effect:
        errors.append(f"{label} effect expected {effect!r}, got {emitted_effect!r}")

    if effect == "shadow":
        if payload.get("status") != "awaiting_confirmation":
            errors.append(f"{label} shadow action did not await confirmation")
        if not payload.get("confirmation_id"):
            errors.append(f"{label} shadow action missing confirmation_id")
    if effect == "block" and payload.get("allowed") is True:
        errors.append(f"{label} forbidden action was allowed")
    if expected_allowed:
        allowed_policy[(surface, action_type, _target(payload))] = index


def _is_policy_event(event_type: object) -> bool:
    return isinstance(event_type, str) and event_type.endswith(".policy_decision")


def _surface(payload: dict, label: str) -> str:
    surface = payload.get("surface")
    if surface:
        return surface
    if "browser_readonly_task" in label:
        return "browser_readonly"
    if "gui_shadow" in label:
        return "desktop_shadow"
    return "desktop_shadow"


def _find_policy_row(rows: list[dict], action_type: str, surface: str) -> dict | None:
    for row in rows:
        if row.get("action_type") != action_type:
            continue
        surfaces = set(row.get("surfaces") or [])
        if "*" in surfaces or surface in surfaces:
            return row
    return None


def _target(payload: dict) -> str:
    return str(payload.get("url") or payload.get("confirmation_id") or "*")


def _require_prior_policy(
    label: str,
    allowed_policy: dict[tuple[str, str, str], int],
    surface: str,
    action_type: str,
    target: str,
    errors: list[str],
) -> None:
    if (surface, action_type, target) in allowed_policy:
        return
    errors.append(
        f"{label} has no prior allowed policy decision for "
        f"{surface}.{action_type} target={target}"
    )
