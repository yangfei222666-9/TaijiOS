from aios.gui_agent import (
    ActionParser,
    DryRunOperator,
    GUIAgent,
    GUIAgentConfig,
    InMemoryConfirmationStore,
    JsonlConfirmationStore,
    ModelResult,
    PolicyEngine,
)
from aios.gui_agent.redaction import contains_secret


class FakeVisualModel:
    def __init__(self, predictions):
        self.predictions = list(predictions)

    def invoke(self, instruction, screenshot, history, previous_response_id=None):
        return ModelResult(prediction=self.predictions.pop(0))


def _fake_token_assignment() -> str:
    return "tok" + "en=" + "abcdef" + "ghi"


def test_action_parser_extracts_coords_from_ui_tars_prediction():
    parser = ActionParser()
    actions = parser.parse(
        "Thought: click the search box\nAction: click(start_box='[250, 100, 350, 200]')",
        screen_width=1920,
        screen_height=1080,
    )

    assert len(actions) == 1
    assert actions[0].action_type == "click"
    assert actions[0].inputs["start_coords"] == (576.0, 162.0)
    assert actions[0].thought == "click the search box"


def test_action_parser_accepts_adjacent_action_lines():
    parser = ActionParser()
    actions = parser.parse(
        "Thought: fill field\nAction: click(start_box='[10, 10]')\n"
        "type(content='hello, world')",
        screen_width=1000,
        screen_height=1000,
    )

    assert [action.action_type for action in actions] == ["click", "type"]
    assert actions[0].inputs["start_coords"] == (10.0, 10.0)
    assert actions[1].inputs["content"] == "hello, world"


def test_gui_agent_stops_for_shadow_mode_confirmation():
    confirmation_store = InMemoryConfirmationStore()
    agent = GUIAgent(
        operator=DryRunOperator(),
        model=FakeVisualModel(
            ["Thought: enter text\nAction: type(content='hello')"]
        ),
        policy=PolicyEngine(shadow_mode=True),
        confirmation_store=confirmation_store,
    )

    result = agent.run("type hello")

    assert result.status == "awaiting_confirmation"
    assert result.confirmation_id
    assert result.steps[0].actions[0].action_type == "type"
    assert result.pending_action == result.steps[0].actions[0]
    assert confirmation_store.get(result.confirmation_id).status == "pending"


def test_gui_agent_can_approve_stored_confirmation():
    operator = DryRunOperator()
    confirmation_store = InMemoryConfirmationStore()
    agent = GUIAgent(
        operator=operator,
        model=FakeVisualModel(
            ["Thought: click target\nAction: click(start_box='[100, 100, 100, 100]')"]
        ),
        policy=PolicyEngine(shadow_mode=True),
        confirmation_store=confirmation_store,
    )

    result = agent.run("click target")
    execution = agent.approve_confirmation(result.confirmation_id, actor="tester")

    assert execution.status == "recorded"
    assert confirmation_store.get(result.confirmation_id).status == "executed"
    assert confirmation_store.get(result.confirmation_id).decided_by == "tester"
    assert [action.action_type for action in operator.executed] == ["click"]


def test_gui_agent_can_execute_approved_shadow_action():
    operator = DryRunOperator()
    agent = GUIAgent(
        operator=operator,
        model=FakeVisualModel(
            ["Thought: click target\nAction: click(start_box='[100, 100, 100, 100]')"]
        ),
        policy=PolicyEngine(shadow_mode=True),
    )

    result = agent.run("click target")
    execution = agent.execute_approved_action(result.pending_action)

    assert execution.status == "recorded"
    assert [action.action_type for action in operator.executed] == ["click"]


def test_gui_agent_can_execute_in_auto_confirmed_dry_run():
    operator = DryRunOperator()
    agent = GUIAgent(
        operator=operator,
        model=FakeVisualModel(
            [
                "Thought: click target\nAction: click(start_box='[100, 100, 100, 100]')",
                "Thought: done\nAction: finished()",
            ]
        ),
        policy=PolicyEngine(shadow_mode=False),
        config=GUIAgentConfig(auto_execute_confirmed=True),
    )

    result = agent.run("click target")

    assert result.status == "finished"
    assert [action.action_type for action in operator.executed] == ["click"]


def test_gui_agent_blocks_unknown_action():
    agent = GUIAgent(
        operator=DryRunOperator(),
        model=FakeVisualModel(["Thought: risky\nAction: delete_file(path='C:/x')"]),
        policy=PolicyEngine(shadow_mode=False),
    )

    result = agent.run("delete something")

    assert result.status == "blocked"
    assert "not allowed" in result.final_message


def test_jsonl_confirmation_store_replays_latest_state(tmp_path):
    store = JsonlConfirmationStore(tmp_path / "confirmations.jsonl")
    request = store.create(
        instruction="click",
        action=ActionParser().parse("Action: click(start_box='[1,1,1,1]')")[0],
        reason="test",
    )
    store.approve(request.id, "tester")
    store.mark_executed(request.id, "recorded")

    replayed = JsonlConfirmationStore(tmp_path / "confirmations.jsonl")

    assert replayed.get(request.id).status == "executed"
    assert replayed.get(request.id).execution_status == "recorded"


def test_jsonl_confirmation_store_redacts_secret_instruction(tmp_path):
    store = JsonlConfirmationStore(tmp_path / "confirmations.jsonl")
    store.create(
        instruction=f"use {_fake_token_assignment()} for this click",
        action=ActionParser().parse("Action: click(start_box='[1,1,1,1]')")[0],
        reason="test",
    )

    text = (tmp_path / "confirmations.jsonl").read_text(encoding="utf-8")

    assert contains_secret(text) is False
    assert "abcdefghi" not in text
    assert "[REDACTED_SECRET]" in text


def test_gui_agent_treats_model_environment_error_as_terminal():
    agent = GUIAgent(
        operator=DryRunOperator(),
        model=FakeVisualModel(["Thought: environment unavailable\nAction: error_env()"]),
        policy=PolicyEngine(shadow_mode=False),
    )

    result = agent.run("inspect app")

    assert result.status == "error_env"
    assert result.final_message == "environment unavailable"
