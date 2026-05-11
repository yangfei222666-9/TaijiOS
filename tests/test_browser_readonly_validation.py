import json

from aios.gui_agent.browser_readonly_task import BrowserReadonlyTaskRunner
from aios.gui_agent.browser_readonly_validation import validate_browser_readonly_task


def fake_api_key() -> str:
    return "api" + "_key=" + "sk-demo-" + "secret-00000000"


def _run_task(output_dir):
    url = "https://example.taijios.local/report"
    return BrowserReadonlyTaskRunner.offline(
        urls=(url,),
        pages={url: "<html><title>Report</title><body>hello world</body></html>"},
        allowed_hosts={"example.taijios.local"},
        output_dir=output_dir,
    ).run()


def test_validate_browser_readonly_task_accepts_generated_artifacts(tmp_path):
    output_dir = tmp_path / "run"

    _run_task(output_dir)
    result = validate_browser_readonly_task(output_dir)

    assert result.ok is True
    assert result.errors == []


def test_validate_browser_readonly_task_rejects_live_workflow(tmp_path):
    output_dir = tmp_path / "run"
    _run_task(output_dir)
    summary_path = output_dir / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["live_workflow"] = True
    summary_path.write_text(json.dumps(summary), encoding="utf-8")

    result = validate_browser_readonly_task(output_dir)

    assert result.ok is False
    assert any("live_workflow" in error for error in result.errors)


def test_validate_browser_readonly_task_rejects_side_effects(tmp_path):
    output_dir = tmp_path / "run"
    _run_task(output_dir)
    summary_path = output_dir / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["side_effects"] = True
    summary["pages"][0]["side_effect"] = True
    summary_path.write_text(json.dumps(summary), encoding="utf-8")

    result = validate_browser_readonly_task(output_dir)

    assert result.ok is False
    assert any("side_effect" in error for error in result.errors)


def test_validate_browser_readonly_task_rejects_summary_url_outside_allowlist(tmp_path):
    output_dir = tmp_path / "run"
    _run_task(output_dir)
    summary_path = output_dir / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["pages"][0]["url"] = "https://tracker.example/report"
    summary_path.write_text(json.dumps(summary), encoding="utf-8")

    result = validate_browser_readonly_task(output_dir)

    assert result.ok is False
    assert any("outside allowed_hosts" in error for error in result.errors)


def test_validate_browser_readonly_task_rejects_event_url_outside_allowlist(tmp_path):
    output_dir = tmp_path / "run"
    _run_task(output_dir)
    event_flow = output_dir / "event_flow.jsonl"
    events = [
        json.loads(line)
        for line in event_flow.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    for event in events:
        if event.get("type") == "browser_readonly_task.open.completed":
            event["payload"]["url"] = "https://tracker.example/report"
            break
    event_flow.write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )

    result = validate_browser_readonly_task(output_dir)

    assert result.ok is False
    assert any("outside allowed_hosts" in error for error in result.errors)


def test_validate_browser_readonly_task_rejects_secret_artifacts(tmp_path):
    output_dir = tmp_path / "run"
    _run_task(output_dir)
    report_path = output_dir / "browser_readonly_report.md"
    report_path.write_text(
        report_path.read_text(encoding="utf-8") + f"\n{fake_api_key()}\n",
        encoding="utf-8",
    )

    result = validate_browser_readonly_task(output_dir)

    assert result.ok is False
    assert any("secret-like" in error for error in result.errors)


def test_validate_browser_readonly_task_rejects_missing_required_event(tmp_path):
    output_dir = tmp_path / "run"
    _run_task(output_dir)
    event_flow = output_dir / "event_flow.jsonl"
    events = [
        json.loads(line)
        for line in event_flow.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    events = [
        event
        for event in events
        if event.get("type") != "browser_readonly_task.read.completed"
    ]
    event_flow.write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )

    result = validate_browser_readonly_task(output_dir)

    assert result.ok is False
    assert any("missing event types" in error for error in result.errors)
