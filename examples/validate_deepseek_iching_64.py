"""Validate DeepSeek I Ching 64-hexagram artifacts."""

from __future__ import annotations

import json
import sys
import argparse
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from aios.iching.deepseek_runner import resolve_latest_output_dir, validate_iching_run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate DeepSeek I Ching 64-hexagram artifacts."
    )
    parser.add_argument(
        "output_dir",
        nargs="?",
        help="Run directory to validate. Defaults to the latest output pointer.",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Use the latest completed live output pointer or discovered live run.",
    )
    return parser


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args()
    output_dir = (
        Path(args.output_dir)
        if args.output_dir
        else resolve_latest_output_dir(live=args.live)
    )
    result = validate_iching_run(output_dir)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
