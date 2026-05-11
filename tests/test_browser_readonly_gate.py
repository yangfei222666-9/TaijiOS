from aios.gui_agent.browser_readonly_gate import (
    DEFAULT_BROWSER_READONLY_TASK_OUTPUT_DIR,
    main,
    run_browser_readonly_gate,
)


def test_browser_readonly_gate_regenerates_and_validates_artifacts(tmp_path):
    result = run_browser_readonly_gate(output_dir=tmp_path / "browser")

    assert result.ok is True
    assert result.validation.errors == []
    assert result.summary["verdict"] == "browser_readonly_candidate"
    assert result.summary["side_effects"] is False
    assert (tmp_path / "browser" / "event_flow.jsonl").exists()
    assert (tmp_path / "browser" / "summary.json").exists()


def test_browser_readonly_gate_cli_returns_success(tmp_path):
    exit_code = main(["--output-dir", str(tmp_path / "browser")])

    assert exit_code == 0


def test_browser_readonly_gate_default_output_is_ops_check_run():
    assert DEFAULT_BROWSER_READONLY_TASK_OUTPUT_DIR.parts[-3:] == (
        "runs",
        "ops_check",
        "browser_readonly_task_20260511",
    )
