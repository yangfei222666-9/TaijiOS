"""Validate artifacts from the combined GUI agent ops-check gate."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from aios.gui_agent.ops_check_validation import validate_gui_agent_ops_check
from aios.gui_agent.ops_paths import DEFAULT_GUI_AGENT_OPS_CHECK_OUTPUT_DIR


def main() -> int:
    output_dir = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else DEFAULT_GUI_AGENT_OPS_CHECK_OUTPUT_DIR
    )
    result = validate_gui_agent_ops_check(output_dir)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
