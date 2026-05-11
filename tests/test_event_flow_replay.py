import json
from pathlib import Path

from aios.gui_agent.event_flow_replay import replay_event_flows
from aios.gui_agent.ops_check_gate import run_gui_agent_ops_check_gate


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


def _event_flow_paths(result):
    return [
        result.browser_readonly.summary["artifacts"]["event_flow"],
        result.shadow.summary["artifacts"]["event_flow"],
    ]


def test_replay_event_flows_accepts_generated_ops_check_artifacts(tmp_path):
    result = _run_ops_check(tmp_path)

    replay = replay_event_flows(
        _event_flow_paths(result),
        result.policy_manifest_path,
    )

    assert replay.ok is True
    assert replay.errors == []
    assert replay.replayed_policy_events == 5


def test_replay_event_flows_rejects_tampered_policy_decision(tmp_path):
    result = _run_ops_check(tmp_path)
    browser_event_flow = Path(result.browser_readonly.summary["artifacts"]["event_flow"])
    events = [
        json.loads(line)
        for line in browser_event_flow.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    for event in events:
        if event["type"] == "browser_readonly_task.policy_decision":
            event["payload"]["effect"] = "block"
            break
    browser_event_flow.write_text(
        "".join(json.dumps(event) + "\n" for event in events),
        encoding="utf-8",
    )

    replay = replay_event_flows(
        _event_flow_paths(result),
        result.policy_manifest_path,
    )

    assert replay.ok is False
    assert any("effect expected 'allow'" in error for error in replay.errors)


def test_replay_event_flows_requires_policy_before_read(tmp_path):
    result = _run_ops_check(tmp_path)
    browser_event_flow = Path(result.browser_readonly.summary["artifacts"]["event_flow"])
    events = [
        json.loads(line)
        for line in browser_event_flow.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    events = [
        event
        for event in events
        if not (
            event["type"] == "browser_readonly_task.policy_decision"
            and event["payload"].get("action_type") == "read_current_page"
        )
    ]
    browser_event_flow.write_text(
        "".join(json.dumps(event) + "\n" for event in events),
        encoding="utf-8",
    )

    replay = replay_event_flows(
        _event_flow_paths(result),
        result.policy_manifest_path,
    )

    assert replay.ok is False
    assert any("read_current_page" in error for error in replay.errors)
