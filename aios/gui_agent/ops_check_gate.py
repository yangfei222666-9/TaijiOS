"""Combined ops-check gate for TaijiOS GUI agent integrations."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .browser_readonly_gate import BrowserReadonlyGateResult, run_browser_readonly_gate
from .ops_paths import (
    DEFAULT_BROWSER_READONLY_TASK_OUTPUT_DIR,
    DEFAULT_GUI_AGENT_OPS_CHECK_OUTPUT_DIR,
    DEFAULT_READONLY_ROOT,
    DEFAULT_SHADOW_POC_OUTPUT_DIR,
)
from .poc_gate import GateResult, run_shadow_mode_gate
from .policy_manifest import write_policy_manifest
from .redaction import contains_secret, redact_secrets


@dataclass
class OpsCheckGateResult:
    """Combined result for GUI agent ops-check gates."""

    output_dir: Path
    shadow: GateResult
    browser_readonly: BrowserReadonlyGateResult
    policy_manifest_path: Path
    summary_path: Path

    @property
    def ok(self) -> bool:
        return self.shadow.ok and self.browser_readonly.ok

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "verdict": "gui_agent_ops_check_candidate",
            "learning_only": True,
            "judgment": False,
            "paper_buy": False,
            "trade": False,
            "promote": False,
            "live_workflow": False,
            "side_effects": False,
            "secret_detected": False,
            "output_dir": str(self.output_dir),
            "summary": str(self.summary_path),
            "policy_manifest": str(self.policy_manifest_path),
            "gates": {
                "shadow_mode_browser_poc": self.shadow.to_dict(),
                "browser_readonly_task": self.browser_readonly.to_dict(),
            },
        }


def run_gui_agent_ops_check_gate(
    output_dir: str | Path = DEFAULT_GUI_AGENT_OPS_CHECK_OUTPUT_DIR,
    shadow_output_dir: str | Path = DEFAULT_SHADOW_POC_OUTPUT_DIR,
    browser_output_dir: str | Path = DEFAULT_BROWSER_READONLY_TASK_OUTPUT_DIR,
    readonly_root: str | Path = DEFAULT_READONLY_ROOT,
) -> OpsCheckGateResult:
    """Run all GUI agent ops-check gates and write a combined summary."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    summary_path = output_path / "summary.json"
    policy_manifest_path = output_path / "policy_matrix.json"
    if summary_path.exists():
        summary_path.unlink()
    if policy_manifest_path.exists():
        policy_manifest_path.unlink()

    shadow = run_shadow_mode_gate(
        output_dir=shadow_output_dir,
        readonly_root=readonly_root,
    )
    browser_readonly = run_browser_readonly_gate(output_dir=browser_output_dir)
    write_policy_manifest(policy_manifest_path)

    result = OpsCheckGateResult(
        output_dir=output_path,
        shadow=shadow,
        browser_readonly=browser_readonly,
        policy_manifest_path=policy_manifest_path,
        summary_path=summary_path,
    )
    summary = redact_secrets(result.to_dict())
    summary["secret_detected"] = contains_secret(summary)
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run all TaijiOS GUI agent ops-check gates.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_GUI_AGENT_OPS_CHECK_OUTPUT_DIR),
        help="Directory where the combined ops-check summary is written.",
    )
    parser.add_argument(
        "--shadow-output-dir",
        default=str(DEFAULT_SHADOW_POC_OUTPUT_DIR),
        help="Directory where shadow-mode POC artifacts are regenerated.",
    )
    parser.add_argument(
        "--browser-output-dir",
        default=str(DEFAULT_BROWSER_READONLY_TASK_OUTPUT_DIR),
        help="Directory where browser read-only task artifacts are regenerated.",
    )
    parser.add_argument(
        "--readonly-root",
        default=str(DEFAULT_READONLY_ROOT),
        help="Directory sampled by the file read-only task in the shadow POC.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_gui_agent_ops_check_gate(
        output_dir=args.output_dir,
        shadow_output_dir=args.shadow_output_dir,
        browser_output_dir=args.browser_output_dir,
        readonly_root=args.readonly_root,
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
