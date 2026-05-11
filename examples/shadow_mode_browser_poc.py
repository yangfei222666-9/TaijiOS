"""Run the TaijiOS UI-TARS shadow-mode browser POC."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from aios.gui_agent.poc_gate import DEFAULT_OUTPUT_DIR, DEFAULT_READONLY_ROOT
from aios.gui_agent.shadow_poc import ShadowModeBrowserPOC


def main() -> None:
    summary = ShadowModeBrowserPOC(
        output_dir=DEFAULT_OUTPUT_DIR,
        readonly_root=DEFAULT_READONLY_ROOT,
    ).run()
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
