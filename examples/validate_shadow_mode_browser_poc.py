"""Validate artifacts from the TaijiOS shadow-mode browser POC."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from aios.gui_agent.poc_gate import DEFAULT_OUTPUT_DIR
from aios.gui_agent.poc_validation import validate_shadow_mode_poc


def main() -> int:
    output_dir = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else DEFAULT_OUTPUT_DIR
    )
    result = validate_shadow_mode_poc(output_dir)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
