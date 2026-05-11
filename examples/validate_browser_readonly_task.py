"""Validate artifacts from the browser read-only task runner."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from aios.gui_agent.browser_readonly_validation import validate_browser_readonly_task
from aios.gui_agent.ops_paths import DEFAULT_BROWSER_READONLY_TASK_OUTPUT_DIR


DEFAULT_OUTPUT_DIR = DEFAULT_BROWSER_READONLY_TASK_OUTPUT_DIR


def main() -> int:
    output_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUTPUT_DIR
    result = validate_browser_readonly_task(output_dir)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
