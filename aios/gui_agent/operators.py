"""Operator abstractions for GUI execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from .actions import Action


@dataclass(frozen=True)
class Screenshot:
    """Screenshot payload sent to a visual model."""

    base64: str
    width: int
    height: int
    scale_factor: float = 1.0
    mime: str = "image/png"


@dataclass(frozen=True)
class ExecutionResult:
    """Result returned by an operator after executing or recording an action."""

    status: str = "executed"
    message: str = ""
    metadata: dict = field(default_factory=dict)


class Operator(Protocol):
    """A TaijiOS GUI operator."""

    def screenshot(self) -> Screenshot:
        """Capture the current target state."""

    def execute(self, action: Action) -> ExecutionResult:
        """Execute an approved action."""


class DryRunOperator:
    """Safe shadow-mode operator used for POC and policy validation."""

    def __init__(
        self,
        screenshot: Screenshot | None = None,
    ):
        self._screenshot = screenshot or Screenshot(
            base64="iVBORw0KGgo=",
            width=1000,
            height=1000,
            scale_factor=1.0,
        )
        self.executed: list[Action] = []

    def screenshot(self) -> Screenshot:
        return self._screenshot

    def execute(self, action: Action) -> ExecutionResult:
        self.executed.append(action)
        return ExecutionResult(
            status="recorded",
            message="dry-run action recorded",
            metadata={
                "action_type": action.action_type,
                "inputs": dict(action.inputs),
            },
        )
