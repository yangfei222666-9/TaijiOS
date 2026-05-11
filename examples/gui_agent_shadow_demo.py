"""Safe GUI agent shadow-mode demo.

Run from the repository root:

    python examples/gui_agent_shadow_demo.py

The demo does not move the mouse or type text. It creates an auditable
confirmation request, approves it, and records a dry-run execution.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from aios.gui_agent import (
    DryRunOperator,
    GUIAgent,
    JsonlConfirmationStore,
    ModelResult,
    PolicyEngine,
)


class ScriptedVisualModel:
    """Deterministic model used to demonstrate the UI-TARS loop."""

    def invoke(self, instruction, screenshot, history, previous_response_id=None):
        return ModelResult(
            prediction=(
                "Thought: I will click the visible target in shadow mode.\n"
                "Action: click(start_box='[100, 100, 160, 160]')"
            )
        )


def main() -> None:
    output_dir = Path("data/gui_agent_shadow_demo")
    output_dir.mkdir(parents=True, exist_ok=True)
    confirmations_path = output_dir / "gui_agent_confirmations.jsonl"

    operator = DryRunOperator()
    confirmation_store = JsonlConfirmationStore(confirmations_path)
    agent = GUIAgent(
        operator=operator,
        model=ScriptedVisualModel(),
        policy=PolicyEngine(shadow_mode=True),
        confirmation_store=confirmation_store,
    )

    run = agent.run("Click the target safely")
    print(json.dumps({
        "status": run.status,
        "confirmation_id": run.confirmation_id,
        "pending_action": (
            run.pending_action.action_type if run.pending_action else None
        ),
    }, ensure_ascii=False, indent=2))

    if run.status == "awaiting_confirmation":
        execution = agent.approve_confirmation(run.confirmation_id, actor="demo")
        print(json.dumps({
            "approved": run.confirmation_id,
            "execution_status": execution.status,
            "executed_actions": [action.action_type for action in operator.executed],
            "confirmation_log": str(confirmations_path),
        }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
