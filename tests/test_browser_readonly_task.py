import json

from aios.gui_agent.actions import Action
from aios.gui_agent.browser_adapter import BrowserActionResult
from aios.gui_agent.browser_readonly_task import (
    BrowserReadonlyTask,
    BrowserReadonlyTaskRunner,
)
from aios.gui_agent.redaction import contains_secret


def fake_token() -> str:
    return "tok" + "en=" + "abcdef" + "ghi"


def fake_api_key() -> str:
    return "api" + "_key=" + "sk-demo-" + "secret-00000000"


def test_browser_readonly_task_writes_parseable_artifacts(tmp_path):
    url = "https://example.taijios.local/report"
    output_dir = tmp_path / "run"

    summary = BrowserReadonlyTaskRunner.offline(
        urls=(url,),
        pages={
            url: (
                f"<html><title>Report {fake_token()}</title>"
                f"<body>Visible text {fake_api_key()}</body></html>"
            )
        },
        allowed_hosts={"example.taijios.local"},
        output_dir=output_dir,
    ).run()

    assert summary["verdict"] == "browser_readonly_candidate"
    assert summary["status"] == "completed"
    assert summary["side_effects"] is False
    assert summary["secret_detected"] is False
    assert summary["trade"] is False
    assert summary["pages"][0]["status"] == "completed"
    assert summary["pages"][0]["network"] is False
    assert contains_secret(summary) is False

    event_flow = output_dir / "event_flow.jsonl"
    summary_path = output_dir / "summary.json"
    report_path = output_dir / "browser_readonly_report.md"
    assert event_flow.exists()
    assert summary_path.exists()
    assert report_path.exists()

    events = [json.loads(line) for line in event_flow.read_text(encoding="utf-8").splitlines()]
    assert {event["type"] for event in events} >= {
        "browser_readonly_task.started",
        "browser_readonly_task.policy_decision",
        "browser_readonly_task.open.requested",
        "browser_readonly_task.open.completed",
        "browser_readonly_task.read.completed",
        "browser_readonly_task.completed",
    }
    assert json.loads(summary_path.read_text(encoding="utf-8"))["status"] == "completed"
    assert "Side effects: false" in report_path.read_text(encoding="utf-8")


class SpyAdapter:
    def __init__(self):
        self.execute_calls: list[Action] = []
        self.closed = False

    def execute(self, action: Action) -> BrowserActionResult:
        self.execute_calls.append(action)
        return BrowserActionResult(status="blocked", reason="unexpected call")

    def close(self) -> None:
        self.closed = True


def test_browser_readonly_task_blocks_disallowed_host_before_adapter_execution(tmp_path):
    adapter = SpyAdapter()
    runner = BrowserReadonlyTaskRunner(
        task=BrowserReadonlyTask(
            urls=("https://other.example/report",),
            allowed_hosts=frozenset({"example.taijios.local"}),
        ),
        output_dir=tmp_path / "run",
        adapter=adapter,
    )

    summary = runner.run()

    assert summary["status"] == "blocked"
    assert summary["pages"][0]["status"] == "blocked"
    assert "allowlist" in summary["errors"][0]
    assert adapter.execute_calls == []
    assert adapter.closed is True


def test_browser_readonly_task_blocks_secret_url_before_adapter_execution(tmp_path):
    adapter = SpyAdapter()
    runner = BrowserReadonlyTaskRunner(
        task=BrowserReadonlyTask(
            urls=(f"https://example.taijios.local/report?{fake_token()}",),
            allowed_hosts=frozenset({"example.taijios.local"}),
        ),
        output_dir=tmp_path / "run",
        adapter=adapter,
    )

    summary = runner.run()

    assert summary["status"] == "blocked"
    assert "secret-like" in summary["errors"][0]
    assert adapter.execute_calls == []
    assert adapter.closed is True
    assert contains_secret(summary) is False


def test_browser_readonly_task_records_adapter_block(tmp_path):
    adapter = SpyAdapter()
    runner = BrowserReadonlyTaskRunner(
        task=BrowserReadonlyTask(
            urls=("https://example.taijios.local/report",),
            allowed_hosts=frozenset({"example.taijios.local"}),
        ),
        output_dir=tmp_path / "run",
        adapter=adapter,
    )

    summary = runner.run()

    assert summary["status"] == "blocked"
    assert summary["pages"][0]["reason"] == "unexpected call"
    assert [action.action_type for action in adapter.execute_calls] == ["navigate"]
    assert adapter.closed is True
