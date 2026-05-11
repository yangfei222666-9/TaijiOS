"""Validation gate for the combined GUI agent ops-check summary."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .browser_readonly_validation import validate_browser_readonly_task
from .event_flow_replay import replay_event_flows
from .ops_paths import OPS_CHECK_ROOT
from .poc_validation import validate_shadow_mode_poc
from .redaction import contains_secret


REQUIRED_GATES = {
    "shadow_mode_browser_poc",
    "browser_readonly_task",
}


@dataclass
class OpsCheckValidationResult:
    """Result of validating a combined GUI agent ops-check run."""

    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checked_files: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "errors": self.errors,
            "warnings": self.warnings,
            "checked_files": self.checked_files,
        }


def validate_gui_agent_ops_check(
    output_dir: str | Path,
    *,
    require_data_root: bool | None = None,
    require_ops_root: bool | None = None,
) -> OpsCheckValidationResult:
    """Validate the combined ops-check summary and child gate artifacts."""
    if require_ops_root is None:
        require_ops_root = True if require_data_root is None else require_data_root

    output_dir = Path(output_dir)
    summary_path = output_dir / "summary.json"
    errors: list[str] = []
    warnings: list[str] = []
    checked_files = [str(summary_path)]

    if not summary_path.exists():
        errors.append("missing artifact: summary.json")
        return OpsCheckValidationResult(False, errors, warnings, checked_files)

    summary = _load_json(summary_path, errors, "summary")
    if require_ops_root:
        _validate_under_ops_root(summary_path, errors, "summary")

    _validate_summary(summary, errors)
    policy_manifest_path = _policy_manifest_path(output_dir, summary)
    checked_files.append(str(policy_manifest_path))
    if require_ops_root:
        _validate_under_ops_root(policy_manifest_path, errors, "policy manifest")
    policy_manifest = _load_existing_json(
        policy_manifest_path,
        errors,
        "policy manifest",
    )
    _validate_policy_manifest(policy_manifest, errors)
    child_files = _validate_child_gates(summary, errors, warnings, require_ops_root)
    checked_files.extend(child_files)
    replay_paths = _event_flow_paths_from_summary(summary)
    if require_ops_root:
        for replay_path in replay_paths:
            _validate_under_ops_root(Path(replay_path), errors, "event flow")
    replay = replay_event_flows(replay_paths, policy_manifest_path)
    checked_files.extend(replay.checked_files)
    errors.extend(f"event_flow_replay: {error}" for error in replay.errors)
    warnings.extend(f"event_flow_replay: {warning}" for warning in replay.warnings)

    if contains_secret(summary):
        errors.append("secret-like value found in combined ops-check summary")
    if contains_secret(policy_manifest):
        errors.append("secret-like value found in policy manifest")

    return OpsCheckValidationResult(
        ok=not errors,
        errors=errors,
        warnings=warnings,
        checked_files=_dedupe(checked_files),
    )


def _load_json(path: Path, errors: list[str], label: str) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        errors.append(f"{label} is not valid JSON: {exc}")
        return {}


def _load_existing_json(path: Path, errors: list[str], label: str) -> dict:
    if not path.exists():
        errors.append(f"missing artifact: {path.name}")
        return {}
    return _load_json(path, errors, label)


def _policy_manifest_path(output_dir: Path, summary: dict) -> Path:
    manifest = summary.get("policy_manifest")
    if manifest:
        return Path(manifest)
    return output_dir / "policy_matrix.json"


def _validate_summary(summary: dict, errors: list[str]) -> None:
    expected_flags = {
        "ok": True,
        "verdict": "gui_agent_ops_check_candidate",
        "learning_only": True,
        "judgment": False,
        "paper_buy": False,
        "trade": False,
        "promote": False,
        "live_workflow": False,
        "side_effects": False,
        "secret_detected": False,
    }
    for key, expected in expected_flags.items():
        if summary.get(key) != expected:
            errors.append(f"summary.{key} expected {expected!r}, got {summary.get(key)!r}")

    gates = summary.get("gates") or {}
    missing = sorted(REQUIRED_GATES - set(gates))
    if missing:
        errors.append(f"summary.gates missing required gates: {missing}")

    for gate_name in sorted(REQUIRED_GATES & set(gates)):
        gate = gates.get(gate_name) or {}
        if gate.get("ok") is not True:
            errors.append(f"summary.gates.{gate_name}.ok expected True")
        validation = gate.get("validation") or {}
        if validation.get("ok") is not True:
            errors.append(f"summary.gates.{gate_name}.validation.ok expected True")


def _validate_policy_manifest(manifest: dict, errors: list[str]) -> None:
    if not manifest:
        return

    if manifest.get("schema_version") != 1:
        errors.append(
            "policy_manifest.schema_version expected 1, "
            f"got {manifest.get('schema_version')!r}"
        )
    if manifest.get("verdict") != "policy_matrix_candidate":
        errors.append(
            "policy_manifest.verdict expected 'policy_matrix_candidate', "
            f"got {manifest.get('verdict')!r}"
        )

    controls = manifest.get("required_controls") or {}
    required_controls = {
        "secret_inputs_blocked",
        "live_workflow_non_terminal_blocked",
        "desktop_gui_requires_confirmation",
        "browser_readonly_no_side_effect_actions",
    }
    for control in sorted(required_controls):
        if controls.get(control) is not True:
            errors.append(f"policy_manifest.required_controls.{control} expected True")

    rows = manifest.get("rules") or []
    if not isinstance(rows, list):
        errors.append("policy_manifest.rules expected list")
        return

    required_forbidden = {
        "trade",
        "buy",
        "sell",
        "delete_file",
        "move_file",
        "copy_secret",
        "paste_secret",
    }
    for action_type in sorted(required_forbidden):
        if not _has_policy_row(rows, action_type, "block"):
            errors.append(f"policy_manifest missing block row for {action_type}")

    for action_type in ("navigate", "read_current_page"):
        if not _has_policy_row(rows, action_type, "allow", surface="browser_readonly"):
            errors.append(
                "policy_manifest missing browser_readonly allow row for "
                f"{action_type}"
            )

    for action_type in ("click", "type", "hotkey"):
        if not _has_policy_row(
            rows,
            action_type,
            "shadow",
            surface="desktop_shadow",
            requires_confirmation=True,
        ):
            errors.append(
                "policy_manifest missing desktop shadow confirmation row for "
                f"{action_type}"
            )


def _has_policy_row(
    rows: list[dict],
    action_type: str,
    effect: str,
    *,
    surface: str | None = None,
    requires_confirmation: bool | None = None,
) -> bool:
    for row in rows:
        if row.get("action_type") != action_type:
            continue
        if row.get("effect") != effect:
            continue
        surfaces = set(row.get("surfaces") or [])
        if surface is not None and "*" not in surfaces and surface not in surfaces:
            continue
        if (
            requires_confirmation is not None
            and row.get("requires_confirmation") is not requires_confirmation
        ):
            continue
        return True
    return False


def _validate_child_gates(
    summary: dict,
    errors: list[str],
    warnings: list[str],
    require_ops_root: bool,
) -> list[str]:
    checked_files: list[str] = []
    gates = summary.get("gates") or {}

    shadow = gates.get("shadow_mode_browser_poc") or {}
    shadow_output = shadow.get("output_dir")
    if shadow_output:
        if require_ops_root:
            _validate_under_ops_root(Path(shadow_output), errors, "shadow output_dir")
        result = validate_shadow_mode_poc(shadow_output)
        checked_files.extend(result.checked_files)
        errors.extend(f"shadow_mode_browser_poc: {error}" for error in result.errors)
        warnings.extend(f"shadow_mode_browser_poc: {warning}" for warning in result.warnings)

    browser = gates.get("browser_readonly_task") or {}
    browser_output = browser.get("output_dir")
    if browser_output:
        if require_ops_root:
            _validate_under_ops_root(Path(browser_output), errors, "browser output_dir")
        result = validate_browser_readonly_task(browser_output)
        checked_files.extend(result.checked_files)
        errors.extend(f"browser_readonly_task: {error}" for error in result.errors)
        warnings.extend(f"browser_readonly_task: {warning}" for warning in result.warnings)

    return checked_files


def _event_flow_paths_from_summary(summary: dict) -> list[str]:
    paths: list[str] = []
    gates = summary.get("gates") or {}
    for gate_name in sorted(REQUIRED_GATES):
        gate = gates.get(gate_name) or {}
        gate_summary = gate.get("summary") or {}
        artifacts = gate_summary.get("artifacts") or {}
        event_flow = artifacts.get("event_flow")
        if event_flow:
            paths.append(event_flow)
    return paths


def _validate_under_ops_root(path: Path, errors: list[str], label: str) -> None:
    try:
        path.resolve().relative_to(OPS_CHECK_ROOT.resolve())
    except ValueError:
        errors.append(f"{label} is outside ops_check root: {path}")


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped
