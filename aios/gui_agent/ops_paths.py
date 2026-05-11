"""Shared filesystem paths for GUI agent ops-check artifacts."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
OPS_CHECK_ROOT = REPO_ROOT / "runs" / "ops_check"
# Backward-compatible alias for older callers; GUI agent gates must still
# write to runs/ops_check, not the generic runtime data directory.
DATA_ROOT = OPS_CHECK_ROOT
DEFAULT_READONLY_ROOT = REPO_ROOT / "docs"

DEFAULT_SHADOW_POC_OUTPUT_DIR = OPS_CHECK_ROOT / "shadow_mode_browser_poc_20260511"
DEFAULT_BROWSER_READONLY_TASK_OUTPUT_DIR = OPS_CHECK_ROOT / "browser_readonly_task_20260511"
DEFAULT_GUI_AGENT_OPS_CHECK_OUTPUT_DIR = OPS_CHECK_ROOT / "gui_agent_ops_check_20260511"
