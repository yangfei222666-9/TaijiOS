"""A minimal UI-TARS style GUI agent loop for TaijiOS."""

from __future__ import annotations

from dataclasses import dataclass, field

from aios.core.event import Event

from .actions import Action, ActionParser
from .confirmation import ConfirmationStore
from .models import ModelResult, VisualModel
from .operators import ExecutionResult, Operator
from .policy import PolicyDecision, PolicyEngine
from .redaction import redact_secrets


@dataclass
class GUIAgentConfig:
    """Configuration for a TaijiOS GUI agent run."""

    max_loop_count: int = 15
    auto_execute_confirmed: bool = False
    source: str = "gui_agent"


@dataclass
class GUIAgentStep:
    """One observe-think-act step."""

    loop_index: int
    prediction: str
    actions: list[Action]
    decisions: list[PolicyDecision] = field(default_factory=list)
    results: list[ExecutionResult] = field(default_factory=list)


@dataclass
class GUIAgentRun:
    """Final run state."""

    status: str
    steps: list[GUIAgentStep]
    final_message: str = ""
    previous_response_id: str | None = None
    confirmation_id: str | None = None

    @property
    def pending_action(self) -> Action | None:
        """Return the first action waiting for external confirmation."""
        if self.status != "awaiting_confirmation":
            return None
        for step in reversed(self.steps):
            for action, decision in zip(step.actions, step.decisions):
                if decision.allowed and decision.requires_confirmation:
                    return action
        return None


class GUIAgent:
    """Coordinates screenshot, visual model, parser, policy and operator."""

    def __init__(
        self,
        operator: Operator,
        model: VisualModel,
        policy: PolicyEngine | None = None,
        parser: ActionParser | None = None,
        event_bus=None,
        confirmation_store: ConfirmationStore | None = None,
        config: GUIAgentConfig | None = None,
    ):
        self.operator = operator
        self.model = model
        self.policy = policy or PolicyEngine()
        self.parser = parser or ActionParser()
        self.event_bus = event_bus
        self.confirmation_store = confirmation_store
        self.config = config or GUIAgentConfig()

    def run(self, instruction: str) -> GUIAgentRun:
        self._emit("gui_agent.started", {"instruction": instruction})
        history: list[dict] = []
        steps: list[GUIAgentStep] = []
        previous_response_id: str | None = None

        for loop_index in range(1, self.config.max_loop_count + 1):
            screenshot = self.operator.screenshot()
            self._emit(
                "gui_agent.screenshot",
                {
                    "loop_index": loop_index,
                    "width": screenshot.width,
                    "height": screenshot.height,
                    "scale_factor": screenshot.scale_factor,
                },
            )

            result: ModelResult = self.model.invoke(
                instruction=instruction,
                screenshot=screenshot,
                history=history,
                previous_response_id=previous_response_id,
            )
            previous_response_id = result.response_id or previous_response_id
            actions = self.parser.parse(
                result.prediction,
                screen_width=screenshot.width,
                screen_height=screenshot.height,
            )
            step = GUIAgentStep(
                loop_index=loop_index,
                prediction=result.prediction,
                actions=actions,
            )
            steps.append(step)
            self._emit(
                "gui_agent.model_response",
                {
                    "loop_index": loop_index,
                    "action_count": len(actions),
                    "prompt_tokens": result.prompt_tokens,
                    "completion_tokens": result.completion_tokens,
                },
            )

            if not actions:
                self._emit("gui_agent.no_action", {"loop_index": loop_index})
                return GUIAgentRun(
                    status="error",
                    steps=steps,
                    final_message="model returned no parseable action",
                    previous_response_id=previous_response_id,
                )

            for action in actions:
                decision = self.policy.evaluate(action)
                step.decisions.append(decision)
                self._emit(
                    "gui_agent.policy_decision",
                    {
                        "loop_index": loop_index,
                        "action_type": action.action_type,
                        "allowed": decision.allowed,
                        "requires_confirmation": decision.requires_confirmation,
                        "reason": decision.reason,
                    },
                )
                if not decision.allowed:
                    return GUIAgentRun(
                        status="blocked",
                        steps=steps,
                        final_message=decision.reason,
                        previous_response_id=previous_response_id,
                    )

                if action.is_terminal:
                    status_by_action = {
                        "finished": "finished",
                        "call_user": "needs_user",
                        "error_env": "error_env",
                        "max_loop": "max_loop",
                        "user_stop": "stopped",
                    }
                    status = status_by_action.get(action.action_type, "finished")
                    self._emit(
                        f"gui_agent.{action.action_type}",
                        {
                            "loop_index": loop_index,
                            "action_type": action.action_type,
                        },
                    )
                    return GUIAgentRun(
                        status=status,
                        steps=steps,
                        final_message=action.thought,
                        previous_response_id=previous_response_id,
                    )

                if decision.requires_confirmation and not self.config.auto_execute_confirmed:
                    confirmation_id = None
                    if self.confirmation_store is not None:
                        confirmation = self.confirmation_store.create(
                            instruction=instruction,
                            action=action,
                            reason=decision.reason,
                            metadata={
                                "loop_index": loop_index,
                                "source": self.config.source,
                            },
                        )
                        confirmation_id = confirmation.id

                    self._emit(
                        "gui_agent.awaiting_confirmation",
                        {
                            "loop_index": loop_index,
                            "confirmation_id": confirmation_id,
                            "action_type": action.action_type,
                            "inputs": action.inputs,
                        },
                    )
                    return GUIAgentRun(
                        status="awaiting_confirmation",
                        steps=steps,
                        final_message=decision.reason,
                        previous_response_id=previous_response_id,
                        confirmation_id=confirmation_id,
                    )

                execution = self.operator.execute(action)
                step.results.append(execution)
                self._emit(
                    "gui_agent.action_executed",
                    {
                        "loop_index": loop_index,
                        "action_type": action.action_type,
                        "status": execution.status,
                    },
                )

            history.append({"role": "assistant", "content": result.prediction})

        self._emit("gui_agent.max_loop", {"max_loop_count": self.config.max_loop_count})
        return GUIAgentRun(
            status="max_loop",
            steps=steps,
            final_message="reached max loop count",
            previous_response_id=previous_response_id,
        )

    def approve_confirmation(
        self,
        confirmation_id: str,
        actor: str = "user",
    ) -> ExecutionResult:
        """Approve and execute a stored pending confirmation request."""
        if self.confirmation_store is None:
            raise RuntimeError("no confirmation store configured")

        request = self.confirmation_store.get(confirmation_id)
        if request is None:
            raise KeyError(f"confirmation not found: {confirmation_id}")

        decision = self.policy.evaluate(request.action)
        if not decision.allowed:
            self.confirmation_store.reject(confirmation_id, actor, decision.reason)
            raise PermissionError(decision.reason)

        self.confirmation_store.approve(confirmation_id, actor)
        execution = self.execute_approved_action(request.action)
        self.confirmation_store.mark_executed(confirmation_id, execution.status)
        self._emit(
            "gui_agent.confirmation_executed",
            {
                "confirmation_id": confirmation_id,
                "actor": actor,
                "execution_status": execution.status,
            },
        )
        return execution

    def execute_approved_action(self, action: Action | None) -> ExecutionResult:
        """Execute a previously confirmed action while preserving allowlist checks."""
        if action is None:
            raise ValueError("no action supplied for approved execution")

        decision = self.policy.evaluate(action)
        if not decision.allowed:
            raise PermissionError(decision.reason)

        execution = self.operator.execute(action)
        self._emit(
            "gui_agent.action_executed",
            {
                "action_type": action.action_type,
                "status": execution.status,
                "approved": True,
            },
        )
        return execution

    def _emit(self, event_type: str, payload: dict) -> None:
        if self.event_bus is None:
            return
        self.event_bus.emit(Event.create(event_type, self.config.source, redact_secrets(payload)))
