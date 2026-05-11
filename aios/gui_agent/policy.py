"""Policy gates for GUI agent actions."""

from __future__ import annotations

from dataclasses import dataclass, field

from .actions import Action
from .redaction import contains_secret


@dataclass(frozen=True)
class PolicyDecision:
    """Decision returned by a GUI action policy gate."""

    allowed: bool
    reason: str
    requires_confirmation: bool = False
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class PolicyContext:
    """Execution context used by the policy rule matrix."""

    surface: str = "desktop_shadow"
    read_only: bool = False
    live_workflow: bool = False
    workflow_tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class PolicyRule:
    """One row in the GUI action policy matrix."""

    action_type: str
    effect: str
    reason: str
    surfaces: frozenset[str] = frozenset({"*"})
    requires_confirmation: bool = False
    metadata: dict = field(default_factory=dict)

    def matches(self, action: Action, context: PolicyContext) -> bool:
        return (
            self.action_type == action.action_type
            and ("*" in self.surfaces or context.surface in self.surfaces)
        )


class PolicyRuleMatrix:
    """Explicit allow/shadow/block matrix for GUI actions."""

    TERMINAL_ACTIONS = frozenset({"finished", "call_user", "error_env", "max_loop", "user_stop"})
    READ_ONLY_BROWSER_ACTIONS = frozenset({"navigate", "open_url", "read_page", "read_current_page", "wait"})
    DESKTOP_SHADOW_ACTIONS = frozenset(
        {
            "click",
            "left_click",
            "left_single",
            "left_double",
            "double_click",
            "right_click",
            "right_single",
            "drag",
            "scroll",
            "hotkey",
            "type",
            "press",
            "release",
            "navigate",
            "navigate_back",
        }
    )
    FORBIDDEN_ACTIONS = frozenset(
        {
            "delete",
            "delete_file",
            "overwrite_file",
            "move_file",
            "rename_file",
            "trade",
            "buy",
            "sell",
            "purchase",
            "checkout",
            "submit_order",
            "transfer",
            "reveal_secret",
            "copy_secret",
            "paste_secret",
        }
    )

    def __init__(self, rules: list[PolicyRule] | None = None):
        self.rules = rules or self.default_rules()

    @classmethod
    def default(cls) -> "PolicyRuleMatrix":
        return cls(cls.default_rules())

    @classmethod
    def default_rules(cls) -> list[PolicyRule]:
        rules: list[PolicyRule] = []
        rules.extend(
            PolicyRule(
                action_type=action_type,
                effect="block",
                reason="forbidden by TaijiOS GUI safety policy",
            )
            for action_type in sorted(cls.FORBIDDEN_ACTIONS)
        )
        rules.extend(
            PolicyRule(
                action_type=action_type,
                effect="allow",
                reason="terminal action has no external side effect",
            )
            for action_type in sorted(cls.TERMINAL_ACTIONS)
        )
        rules.extend(
            PolicyRule(
                action_type=action_type,
                effect="allow",
                reason="allowed in browser read-only surface",
                surfaces=frozenset({"browser_readonly"}),
            )
            for action_type in sorted(cls.READ_ONLY_BROWSER_ACTIONS)
        )
        rules.extend(
            PolicyRule(
                action_type=action_type,
                effect="shadow",
                reason="desktop GUI action requires TaijiOS policy review",
                surfaces=frozenset({"desktop_shadow", "desktop"}),
                requires_confirmation=True,
            )
            for action_type in sorted(cls.DESKTOP_SHADOW_ACTIONS)
        )
        return rules

    def evaluate(
        self,
        action: Action,
        context: PolicyContext,
        shadow_mode: bool = True,
    ) -> PolicyDecision | None:
        """Return a matrix decision, or None if no row matches."""
        if not action.action_type:
            return PolicyDecision(False, "empty action type")

        if contains_secret(action.inputs):
            return PolicyDecision(
                False,
                "action input contains secret-like value",
                metadata={"action_type": action.action_type, "surface": context.surface},
            )

        if context.live_workflow and action.action_type not in self.TERMINAL_ACTIONS:
            return PolicyDecision(
                False,
                "live workflow is disabled for GUI agent actions",
                metadata={"action_type": action.action_type, "surface": context.surface},
            )

        for rule in self.rules:
            if rule.matches(action, context):
                return self._decision_from_rule(rule, action, context, shadow_mode)

        if context.read_only:
            return PolicyDecision(
                False,
                f"read-only context blocks action: {action.action_type}",
                metadata={"action_type": action.action_type, "surface": context.surface},
            )

        return None

    def to_rows(self) -> list[dict]:
        """Return a stable table representation for docs and audit reports."""
        return [
            {
                "action_type": rule.action_type,
                "effect": rule.effect,
                "surfaces": sorted(rule.surfaces),
                "requires_confirmation": rule.requires_confirmation,
                "reason": rule.reason,
            }
            for rule in self.rules
        ]

    def _decision_from_rule(
        self,
        rule: PolicyRule,
        action: Action,
        context: PolicyContext,
        shadow_mode: bool,
    ) -> PolicyDecision:
        metadata = {
            "action_type": action.action_type,
            "surface": context.surface,
            "effect": rule.effect,
            **rule.metadata,
        }
        if rule.effect == "block":
            return PolicyDecision(False, rule.reason, metadata=metadata)
        if rule.effect == "shadow":
            return PolicyDecision(
                True,
                rule.reason,
                requires_confirmation=True,
                metadata=metadata,
            )
        if rule.effect == "allow":
            requires_confirmation = rule.requires_confirmation
            if shadow_mode and context.surface not in {"browser_readonly"}:
                requires_confirmation = True
            return PolicyDecision(
                True,
                rule.reason,
                requires_confirmation=requires_confirmation,
                metadata=metadata,
            )
        return PolicyDecision(False, f"unknown policy effect: {rule.effect}", metadata=metadata)


class PolicyEngine:
    """Small allowlist policy for TaijiOS GUI action execution."""

    DEFAULT_ALLOWED = frozenset(
        {
            "click",
            "left_click",
            "left_single",
            "left_double",
            "double_click",
            "right_click",
            "right_single",
            "drag",
            "scroll",
            "wait",
            "hotkey",
            "type",
            "press",
            "release",
            "navigate",
            "navigate_back",
            "finished",
            "call_user",
            "error_env",
            "max_loop",
            "user_stop",
        }
    )

    HIGH_RISK = frozenset({"type", "hotkey", "press", "release", "navigate"})

    def __init__(
        self,
        allowed_actions: set[str] | None = None,
        require_confirmation: set[str] | None = None,
        shadow_mode: bool = True,
        rule_matrix: PolicyRuleMatrix | None = None,
        context: PolicyContext | None = None,
    ):
        self.allowed_actions = allowed_actions or set(self.DEFAULT_ALLOWED)
        self.require_confirmation = require_confirmation or set(self.HIGH_RISK)
        self.shadow_mode = shadow_mode
        self.rule_matrix = rule_matrix
        self.context = context or PolicyContext()

    def evaluate(self, action: Action) -> PolicyDecision:
        if self.rule_matrix is not None:
            decision = self.rule_matrix.evaluate(
                action,
                self.context,
                shadow_mode=self.shadow_mode,
            )
            if decision is not None:
                return decision

        if not action.action_type:
            return PolicyDecision(False, "empty action type")

        if action.action_type not in self.allowed_actions:
            return PolicyDecision(
                False,
                f"action not allowed: {action.action_type}",
                metadata={"action_type": action.action_type},
            )

        requires_confirmation = (
            self.shadow_mode or action.action_type in self.require_confirmation
        )
        return PolicyDecision(
            True,
            "allowed by GUI policy",
            requires_confirmation=requires_confirmation,
            metadata={"action_type": action.action_type},
        )
