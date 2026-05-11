from aios.gui_agent.poc_gate import DEFAULT_OUTPUT_DIR, main, run_shadow_mode_gate


def test_shadow_mode_gate_regenerates_and_validates_artifacts(tmp_path):
    readonly_root = tmp_path / "readonly"
    readonly_root.mkdir()
    (readonly_root / "note.md").write_text("hello", encoding="utf-8")

    result = run_shadow_mode_gate(
        output_dir=tmp_path / "run",
        readonly_root=readonly_root,
    )

    assert result.ok is True
    assert result.validation.errors == []
    assert result.summary["verdict"] == "review_only_candidate"
    assert result.summary["tasks"]["local_gui_shadow"]["executed"] is False
    assert (tmp_path / "run" / "event_flow.jsonl").exists()
    assert (tmp_path / "run" / "summary.json").exists()


def test_shadow_mode_gate_cli_returns_success(tmp_path):
    readonly_root = tmp_path / "readonly"
    readonly_root.mkdir()

    exit_code = main([
        "--output-dir",
        str(tmp_path / "run"),
        "--readonly-root",
        str(readonly_root),
    ])

    assert exit_code == 0


def test_shadow_mode_gate_default_output_is_ops_check_run():
    assert DEFAULT_OUTPUT_DIR.parts[-3:] == (
        "runs",
        "ops_check",
        "shadow_mode_browser_poc_20260511",
    )
