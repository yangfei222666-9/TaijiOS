"""One-command gate for the browser read-only task runner."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .browser_readonly_task import BrowserReadonlyTaskRunner
from .browser_readonly_validation import (
    BrowserReadonlyValidationResult,
    validate_browser_readonly_task,
)
from .ops_paths import DEFAULT_BROWSER_READONLY_TASK_OUTPUT_DIR


DEFAULT_URL = "https://example.taijios.local/ui-tars-review"
DEFAULT_ALLOWED_HOSTS = frozenset({"example.taijios.local"})
DEMO_QUERY_SECRET = "tok" + "en=" + "abcdef" + "ghi"
DEMO_HEADER_SECRET = "api" + "_key=" + "sk-demo-" + "secret-00000000"
DEFAULT_PAGES = {
    DEFAULT_URL: f"""
    <html>
      <head><title>UI-TARS read-only review</title></head>
      <body>
        <h1>Browser read-only task</h1>
        <p>Read the page and produce a short report.</p>
        <p>Do not leak {DEMO_QUERY_SECRET} or {DEMO_HEADER_SECRET}.</p>
      </body>
    </html>
    """,
}


@dataclass
class BrowserReadonlyGateResult:
    """Combined result for generating and validating browser read-only artifacts."""

    output_dir: Path
    summary: dict
    validation: BrowserReadonlyValidationResult

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


def run_browser_readonly_gate(
    output_dir: str | Path = DEFAULT_BROWSER_READONLY_TASK_OUTPUT_DIR,
) -> BrowserReadonlyGateResult:
    """Regenerate the deterministic browser read-only artifacts and validate them."""
    output_path = Path(output_dir)
    summary = BrowserReadonlyTaskRunner.offline(
        urls=(DEFAULT_URL,),
        pages=DEFAULT_PAGES,
        allowed_hosts=set(DEFAULT_ALLOWED_HOSTS),
        output_dir=output_path,
        instruction="Read the UI-TARS review page and summarize the safety posture.",
    ).run()
    validation = validate_browser_readonly_task(output_path)
    return BrowserReadonlyGateResult(
        output_dir=output_path,
        summary=summary,
        validation=validation,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run and validate the TaijiOS browser read-only task runner.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_BROWSER_READONLY_TASK_OUTPUT_DIR),
        help="Directory where browser read-only artifacts are regenerated.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_browser_readonly_gate(output_dir=args.output_dir)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
