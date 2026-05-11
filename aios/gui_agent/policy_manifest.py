"""Machine-readable policy matrix manifest for GUI agent ops checks."""

from __future__ import annotations

import json
from pathlib import Path

from .policy import PolicyRuleMatrix
from .redaction import redact_secrets


POLICY_MANIFEST_SCHEMA_VERSION = 1


def build_policy_manifest(rule_matrix: PolicyRuleMatrix | None = None) -> dict:
    """Return a stable JSON-serializable policy matrix manifest."""
    matrix = rule_matrix or PolicyRuleMatrix.default()
    return {
        "schema_version": POLICY_MANIFEST_SCHEMA_VERSION,
        "verdict": "policy_matrix_candidate",
        "surfaces": ["browser_readonly", "desktop_shadow", "desktop"],
        "required_controls": {
            "secret_inputs_blocked": True,
            "live_workflow_non_terminal_blocked": True,
            "desktop_gui_requires_confirmation": True,
            "browser_readonly_no_side_effect_actions": True,
        },
        "forbidden_actions": sorted(PolicyRuleMatrix.FORBIDDEN_ACTIONS),
        "browser_readonly_actions": sorted(PolicyRuleMatrix.READ_ONLY_BROWSER_ACTIONS),
        "desktop_shadow_actions": sorted(PolicyRuleMatrix.DESKTOP_SHADOW_ACTIONS),
        "terminal_actions": sorted(PolicyRuleMatrix.TERMINAL_ACTIONS),
        "rules": matrix.to_rows(),
    }


def write_policy_manifest(
    path: str | Path,
    rule_matrix: PolicyRuleMatrix | None = None,
) -> Path:
    """Write the policy matrix manifest and return its path."""
    manifest_path = Path(path)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = redact_secrets(build_policy_manifest(rule_matrix))
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest_path
