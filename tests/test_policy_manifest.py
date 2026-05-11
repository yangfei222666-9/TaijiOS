import json

from aios.gui_agent.policy_manifest import (
    build_policy_manifest,
    write_policy_manifest,
)


def _row_by_action_and_effect(manifest, action_type, effect):
    return [
        row
        for row in manifest["rules"]
        if row["action_type"] == action_type and row["effect"] == effect
    ]


def test_build_policy_manifest_exposes_required_controls():
    manifest = build_policy_manifest()

    assert manifest["schema_version"] == 1
    assert manifest["verdict"] == "policy_matrix_candidate"
    assert manifest["required_controls"] == {
        "secret_inputs_blocked": True,
        "live_workflow_non_terminal_blocked": True,
        "desktop_gui_requires_confirmation": True,
        "browser_readonly_no_side_effect_actions": True,
    }
    assert "trade" in manifest["forbidden_actions"]
    assert "read_current_page" in manifest["browser_readonly_actions"]
    assert "click" in manifest["desktop_shadow_actions"]


def test_build_policy_manifest_contains_auditable_rows():
    manifest = build_policy_manifest()

    trade_rows = _row_by_action_and_effect(manifest, "trade", "block")
    assert trade_rows
    assert trade_rows[0]["surfaces"] == ["*"]

    read_rows = _row_by_action_and_effect(manifest, "read_current_page", "allow")
    assert read_rows
    assert read_rows[0]["surfaces"] == ["browser_readonly"]

    click_rows = _row_by_action_and_effect(manifest, "click", "shadow")
    assert click_rows
    assert click_rows[0]["requires_confirmation"] is True
    assert click_rows[0]["surfaces"] == ["desktop", "desktop_shadow"]


def test_write_policy_manifest_round_trips_json(tmp_path):
    path = write_policy_manifest(tmp_path / "policy_matrix.json")

    manifest = json.loads(path.read_text(encoding="utf-8"))

    assert path.name == "policy_matrix.json"
    assert manifest["schema_version"] == 1
    assert manifest["required_controls"]["secret_inputs_blocked"] is True
