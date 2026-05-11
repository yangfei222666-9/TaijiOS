import json

from aios.gui_agent.redaction import contains_secret
from aios.gui_agent.shadow_poc import ShadowModeBrowserPOC


def fake_token() -> str:
    return "tok" + "en=" + "abcdef" + "ghi"


def fake_api_key() -> str:
    return "api" + "_key=" + "sk-very-" + "secret-token"


def test_shadow_mode_browser_poc_writes_parseable_artifacts(tmp_path):
    readonly_root = tmp_path / "readonly"
    readonly_root.mkdir()
    (readonly_root / "note.md").write_text("hello", encoding="utf-8")

    summary = ShadowModeBrowserPOC(
        output_dir=tmp_path / "run",
        readonly_root=readonly_root,
    ).run()

    assert summary["verdict"] == "review_only_candidate"
    assert summary["learning_only"] is True
    assert summary["judgment"] is False
    assert summary["paper_buy"] is False
    assert summary["trade"] is False
    assert summary["promote"] is False
    assert summary["live_workflow"] is False
    assert summary["secret_detected"] is False
    assert summary["tasks"]["local_gui_shadow"]["status"] == "awaiting_confirmation"
    assert summary["tasks"]["local_gui_shadow"]["executed"] is False
    assert summary["tasks"]["file_readonly"]["mutations"] == []

    event_flow = tmp_path / "run" / "event_flow.jsonl"
    events = [json.loads(line) for line in event_flow.read_text(encoding="utf-8").splitlines()]
    assert events
    assert {event["type"] for event in events} >= {
        "browser.open.requested",
        "browser.read.completed",
        "gui_shadow.policy_decision",
        "file_read.completed",
        "poc.completed",
    }

    summary_on_disk = json.loads((tmp_path / "run" / "summary.json").read_text(encoding="utf-8"))
    assert summary_on_disk["secret_detected"] is False


def test_shadow_mode_browser_poc_redacts_browser_secrets(tmp_path):
    readonly_root = tmp_path / "readonly"
    readonly_root.mkdir()
    pages = {
        "https://example.taijios.local/ui-tars-review": (
            f"<html><title>{fake_token()}</title>"
            f"<body>{fake_api_key()}</body></html>"
        )
    }

    ShadowModeBrowserPOC(
        output_dir=tmp_path / "run",
        readonly_root=readonly_root,
        browser_pages=pages,
    ).run()

    artifact_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (tmp_path / "run").glob("*")
        if path.is_file()
    )
    assert fake_api_key() not in artifact_text
    assert fake_token() not in artifact_text
    assert contains_secret(artifact_text) is False
