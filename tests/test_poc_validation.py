import json

from aios.gui_agent.poc_validation import validate_shadow_mode_poc
from aios.gui_agent.shadow_poc import ShadowModeBrowserPOC


def test_validate_shadow_mode_poc_accepts_generated_artifacts(tmp_path):
    readonly_root = tmp_path / "readonly"
    readonly_root.mkdir()
    (readonly_root / "note.md").write_text("hello", encoding="utf-8")
    output_dir = tmp_path / "run"

    ShadowModeBrowserPOC(output_dir=output_dir, readonly_root=readonly_root).run()
    result = validate_shadow_mode_poc(output_dir)

    assert result.ok is True
    assert result.errors == []


def test_validate_shadow_mode_poc_rejects_live_workflow(tmp_path):
    readonly_root = tmp_path / "readonly"
    readonly_root.mkdir()
    output_dir = tmp_path / "run"

    ShadowModeBrowserPOC(output_dir=output_dir, readonly_root=readonly_root).run()
    summary_path = output_dir / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["live_workflow"] = True
    summary_path.write_text(json.dumps(summary), encoding="utf-8")

    result = validate_shadow_mode_poc(output_dir)

    assert result.ok is False
    assert any("live_workflow" in error for error in result.errors)


def test_validate_shadow_mode_poc_rejects_executed_gui_action(tmp_path):
    readonly_root = tmp_path / "readonly"
    readonly_root.mkdir()
    output_dir = tmp_path / "run"

    ShadowModeBrowserPOC(output_dir=output_dir, readonly_root=readonly_root).run()
    summary_path = output_dir / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["tasks"]["local_gui_shadow"]["executed"] = True
    summary_path.write_text(json.dumps(summary), encoding="utf-8")

    result = validate_shadow_mode_poc(output_dir)

    assert result.ok is False
    assert any("executed" in error for error in result.errors)
