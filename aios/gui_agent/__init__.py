"""TaijiOS GUI agent primitives inspired by UI-TARS."""

from .actions import Action, ActionParser
from .agent import GUIAgent, GUIAgentConfig, GUIAgentRun
from .browser_adapter import BrowserActionResult, BrowserPage, ReadOnlyBrowserAdapter
from .browser_readonly_task import (
    BrowserReadonlyArtifacts,
    BrowserReadonlyTask,
    BrowserReadonlyTaskRunner,
)
from .browser_readonly_validation import (
    BrowserReadonlyValidationResult,
    validate_browser_readonly_task,
)
from .confirmation import (
    ConfirmationRequest,
    ConfirmationStore,
    InMemoryConfirmationStore,
    JsonlConfirmationStore,
)
from .event_flow_replay import EventFlowReplayResult, replay_event_flows
from .models import ModelResult, TaijiGatewayVisualModel, VisualModel
from .operators import (
    DryRunOperator,
    ExecutionResult,
    Operator,
    Screenshot,
)
from .playwright_browser_adapter import (
    PlaywrightReadOnlyBrowserAdapter,
    PlaywrightReadOnlyConfig,
)
from .policy import PolicyContext, PolicyDecision, PolicyEngine, PolicyRule, PolicyRuleMatrix
from .policy_manifest import build_policy_manifest, write_policy_manifest
from .redaction import contains_secret, redact_secrets
from .windows_operator import TaijiWindowsOperator, Win32Backend

__all__ = [
    "Action",
    "ActionParser",
    "BrowserActionResult",
    "BrowserPage",
    "BrowserReadonlyArtifacts",
    "BrowserReadonlyTask",
    "BrowserReadonlyTaskRunner",
    "BrowserReadonlyValidationResult",
    "ConfirmationRequest",
    "ConfirmationStore",
    "DryRunOperator",
    "EventFlowReplayResult",
    "ExecutionResult",
    "GUIAgent",
    "GUIAgentConfig",
    "GUIAgentRun",
    "InMemoryConfirmationStore",
    "JsonlConfirmationStore",
    "ModelResult",
    "Operator",
    "PlaywrightReadOnlyBrowserAdapter",
    "PlaywrightReadOnlyConfig",
    "PolicyContext",
    "PolicyDecision",
    "PolicyEngine",
    "PolicyRule",
    "PolicyRuleMatrix",
    "ReadOnlyBrowserAdapter",
    "Screenshot",
    "TaijiGatewayVisualModel",
    "TaijiWindowsOperator",
    "VisualModel",
    "Win32Backend",
    "build_policy_manifest",
    "contains_secret",
    "redact_secrets",
    "replay_event_flows",
    "validate_browser_readonly_task",
    "write_policy_manifest",
]
