import json

from aios.gui_agent.ops_check_gate import main, run_gui_agent_ops_check_gate
from aios.gui_agent.ops_paths import (
    DEFAULT_BROWSER_READONLY_TASK_OUTPUT_DIR,
    DEFAULT_GUI_AGENT_OPS_CHECK_OUTPUT_DIR,
    DEFAULT_SHADOW_POC_OUTPUT_DIR,
)


def test_ops_check_gate_runs_shadow_and_browser_gates(tmp_path):
    readonly_root = tmp_path / "readonly"
    readonly_root.mkdir()
    (readonly_root / "note.md").write_text("hello", encoding="utf-8")

    result = run_gui_agent_ops_check_gate(
        output_dir=tmp_path / "combined",
        shadow_output_dir=tmp_path / "shadow",
        browser_output_dir=tmp_path / "browser",
        readonly_root=readonly_root,
    )

    assert result.ok is True
    assert result.shadow.ok is True
    assert result.browser_readonly.ok is True
    assert result.summary_path.exists()
    assert result.policy_manifest_path.exists()
    summary = json.loads(result.summary_path.read_text(encoding="utf-8"))
    assert summary["ok"] is True
    assert summary["verdict"] == "gui_agent_ops_check_candidate"
    assert summary["learning_only"] is True
    assert summary["judgment"] is False
    assert summary["paper_buy"] is False
    assert summary["trade"] is False
    assert summary["promote"] is False
    assert summary["live_workflow"] is False
    assert summary["side_effects"] is False
    assert summary["secret_detected"] is False
    assert summary["policy_manifest"] == str(result.policy_manifest_path)
    assert summary["gates"]["shadow_mode_browser_poc"]["validation"]["ok"] is True
    assert summary["gates"]["browser_readonly_task"]["validation"]["ok"] is True

    policy_manifest = json.loads(
        result.policy_manifest_path.read_text(encoding="utf-8")
    )
    assert policy_manifest["schema_version"] == 1
    assert policy_manifest["required_controls"]["secret_inputs_blocked"] is True


def test_ops_check_gate_cli_returns_success(tmp_path):
    readonly_root = tmp_path / "readonly"
    readonly_root.mkdir()

    exit_code = main([
        "--output-dir",
        str(tmp_path / "combined"),
        "--shadow-output-dir",
        str(tmp_path / "shadow"),
        "--browser-output-dir",
        str(tmp_path / "browser"),
        "--readonly-root",
        str(readonly_root),
    ])

    assert exit_code == 0


def test_ops_check_default_outputs_are_ops_check_runs():
    assert DEFAULT_GUI_AGENT_OPS_CHECK_OUTPUT_DIR.parts[-3:] == (
        "runs",
        "ops_check",
        "gui_agent_ops_check_20260511",
    )
    assert DEFAULT_SHADOW_POC_OUTPUT_DIR.parts[-3:] == (
        "runs",
        "ops_check",
        "shadow_mode_browser_poc_20260511",
    )
    assert DEFAULT_BROWSER_READONLY_TASK_OUTPUT_DIR.parts[-3:] == (
        "runs",
        "ops_check",
        "browser_readonly_task_20260511",
    )
