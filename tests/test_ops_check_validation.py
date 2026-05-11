import json
from pathlib import Path

import aios.gui_agent.ops_check_validation as ops_check_validation
from aios.gui_agent.ops_check_gate import run_gui_agent_ops_check_gate
from aios.gui_agent.ops_check_validation import validate_gui_agent_ops_check


def fake_api_key() -> str:
    return "api" + "_key=" + "sk-demo-" + "secret-00000000"


def _run_ops_check(tmp_path):
    readonly_root = tmp_path / "readonly"
    readonly_root.mkdir()
    (readonly_root / "note.md").write_text("hello", encoding="utf-8")
    return run_gui_agent_ops_check_gate(
        output_dir=tmp_path / "combined",
        shadow_output_dir=tmp_path / "shadow",
        browser_output_dir=tmp_path / "browser",
        readonly_root=readonly_root,
    )


def test_validate_gui_agent_ops_check_accepts_generated_artifacts(tmp_path):
    result = _run_ops_check(tmp_path)

    validation = validate_gui_agent_ops_check(result.output_dir, require_ops_root=False)

    assert validation.ok is True
    assert validation.errors == []


def test_validate_gui_agent_ops_check_rejects_child_gate_failure(tmp_path):
    result = _run_ops_check(tmp_path)
    summary = json.loads(result.summary_path.read_text(encoding="utf-8"))
    summary["gates"]["browser_readonly_task"]["validation"]["ok"] = False
    result.summary_path.write_text(json.dumps(summary), encoding="utf-8")

    validation = validate_gui_agent_ops_check(result.output_dir, require_ops_root=False)

    assert validation.ok is False
    assert any("browser_readonly_task" in error for error in validation.errors)


def test_validate_gui_agent_ops_check_rejects_top_level_trade_flag(tmp_path):
    result = _run_ops_check(tmp_path)
    summary = json.loads(result.summary_path.read_text(encoding="utf-8"))
    summary["trade"] = True
    result.summary_path.write_text(json.dumps(summary), encoding="utf-8")

    validation = validate_gui_agent_ops_check(result.output_dir, require_ops_root=False)

    assert validation.ok is False
    assert any("summary.trade" in error for error in validation.errors)


def test_validate_gui_agent_ops_check_rejects_secret_summary(tmp_path):
    result = _run_ops_check(tmp_path)
    summary = json.loads(result.summary_path.read_text(encoding="utf-8"))
    summary["debug"] = fake_api_key()
    result.summary_path.write_text(json.dumps(summary), encoding="utf-8")

    validation = validate_gui_agent_ops_check(result.output_dir, require_ops_root=False)

    assert validation.ok is False
    assert any("secret-like" in error for error in validation.errors)


def test_validate_gui_agent_ops_check_rejects_policy_manifest_tampering(tmp_path):
    result = _run_ops_check(tmp_path)
    manifest = json.loads(result.policy_manifest_path.read_text(encoding="utf-8"))
    for row in manifest["rules"]:
        if row["action_type"] == "trade":
            row["effect"] = "allow"
            break
    result.policy_manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    validation = validate_gui_agent_ops_check(result.output_dir, require_ops_root=False)

    assert validation.ok is False
    assert any("block row for trade" in error for error in validation.errors)


def test_validate_gui_agent_ops_check_rejects_event_flow_policy_tampering(tmp_path):
    result = _run_ops_check(tmp_path)
    summary = json.loads(result.summary_path.read_text(encoding="utf-8"))
    event_flow = Path(
        summary["gates"]["browser_readonly_task"]["summary"]["artifacts"]["event_flow"]
    )
    events = [
        json.loads(line)
        for line in event_flow.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    for event in events:
        if event.get("type") == "browser_readonly_task.policy_decision":
            event["payload"]["allowed"] = False
            break
    event_flow.write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )

    validation = validate_gui_agent_ops_check(result.output_dir, require_ops_root=False)

    assert validation.ok is False
    assert any("event_flow_replay" in error for error in validation.errors)


def test_validate_gui_agent_ops_check_rejects_non_ops_root_when_strict(
    tmp_path,
    monkeypatch,
):
    result = _run_ops_check(tmp_path)
    monkeypatch.setattr(ops_check_validation, "OPS_CHECK_ROOT", tmp_path / "allowed")

    validation = validate_gui_agent_ops_check(result.output_dir, require_ops_root=True)

    assert validation.ok is False
    assert any("outside ops_check root" in error for error in validation.errors)
