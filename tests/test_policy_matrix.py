from aios.gui_agent.actions import Action
from aios.gui_agent.policy import PolicyContext, PolicyEngine, PolicyRuleMatrix


def fake_token() -> str:
    return "tok" + "en=" + "abcdef" + "ghi"


def test_policy_matrix_allows_browser_readonly_navigation_without_confirmation():
    policy = PolicyEngine(
        shadow_mode=True,
        rule_matrix=PolicyRuleMatrix.default(),
        context=PolicyContext(surface="browser_readonly", read_only=True),
    )

    decision = policy.evaluate(Action("navigate", {"url": "https://example.taijios.local"}))

    assert decision.allowed is True
    assert decision.requires_confirmation is False
    assert decision.metadata["effect"] == "allow"


def test_policy_matrix_blocks_click_in_browser_readonly_context():
    policy = PolicyEngine(
        rule_matrix=PolicyRuleMatrix.default(),
        context=PolicyContext(surface="browser_readonly", read_only=True),
    )

    decision = policy.evaluate(Action("click", {"start_box": "[1, 1, 2, 2]"}))

    assert decision.allowed is False
    assert "read-only" in decision.reason


def test_policy_matrix_shadows_desktop_click():
    policy = PolicyEngine(
        shadow_mode=True,
        rule_matrix=PolicyRuleMatrix.default(),
        context=PolicyContext(surface="desktop_shadow"),
    )

    decision = policy.evaluate(Action("click", {"start_box": "[1, 1, 2, 2]"}))

    assert decision.allowed is True
    assert decision.requires_confirmation is True
    assert decision.metadata["effect"] == "shadow"


def test_policy_matrix_blocks_forbidden_trade_actions():
    policy = PolicyEngine(
        rule_matrix=PolicyRuleMatrix.default(),
        context=PolicyContext(surface="desktop_shadow"),
    )

    decision = policy.evaluate(Action("trade", {"symbol": "XYZ"}))

    assert decision.allowed is False
    assert "forbidden" in decision.reason


def test_policy_matrix_blocks_secret_inputs():
    policy = PolicyEngine(
        rule_matrix=PolicyRuleMatrix.default(),
        context=PolicyContext(surface="browser_readonly", read_only=True),
    )

    decision = policy.evaluate(Action("navigate", {"url": f"https://example.taijios.local?{fake_token()}"}))

    assert decision.allowed is False
    assert "secret-like" in decision.reason


def test_policy_matrix_blocks_live_workflow_non_terminal_actions():
    policy = PolicyEngine(
        rule_matrix=PolicyRuleMatrix.default(),
        context=PolicyContext(surface="desktop_shadow", live_workflow=True),
    )

    decision = policy.evaluate(Action("click", {"start_box": "[1, 1, 2, 2]"}))

    assert decision.allowed is False
    assert "live workflow" in decision.reason
