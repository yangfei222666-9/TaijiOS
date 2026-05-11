"""One-command gate for the TaijiOS UI-TARS shadow-mode POC."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .ops_paths import DEFAULT_READONLY_ROOT, DEFAULT_SHADOW_POC_OUTPUT_DIR
from .poc_validation import ValidationResult, validate_shadow_mode_poc
from .shadow_poc import ShadowModeBrowserPOC


DEFAULT_OUTPUT_DIR = DEFAULT_SHADOW_POC_OUTPUT_DIR


@dataclass
class GateResult:
    """Combined result for generating and validating shadow-mode artifacts."""

    output_dir: Path
    summary: dict
    validation: ValidationResult

    @property
    def ok(self) -> bool:
        return self.validation.ok

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "output_dir": str(self.output_dir),
            "summary": self.summary,
            "validation": self.validation.to_dict(),
        }


def run_shadow_mode_gate(
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    readonly_root: str | Path = DEFAULT_READONLY_ROOT,
) -> GateResult:
    """Regenerate the deterministic POC artifacts and validate them."""
    output_path = Path(output_dir)
    readonly_path = Path(readonly_root)
    summary = ShadowModeBrowserPOC(
        output_dir=output_path,
        readonly_root=readonly_path,
    ).run()
    validation = validate_shadow_mode_poc(output_path)
    return GateResult(
        output_dir=output_path,
        summary=summary,
        validation=validation,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run and validate the TaijiOS UI-TARS shadow-mode browser POC.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory where POC artifacts are regenerated.",
    )
    parser.add_argument(
        "--readonly-root",
        default=str(DEFAULT_READONLY_ROOT),
        help="Directory sampled by the read-only file task.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_shadow_mode_gate(
        output_dir=args.output_dir,
        readonly_root=args.readonly_root,
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
