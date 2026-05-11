# UI-TARS Agent POC for TaijiOS

This POC imports the UI-TARS mechanism into TaijiOS as a Python-native loop:

```text
instruction -> screenshot -> visual model -> action parser -> policy gate -> operator
```

It deliberately does not embed the Electron desktop app. TaijiOS owns the policy,
permission, audit and operator boundary.

## Added Package

`aios.gui_agent` provides:

- `ActionParser`: parses UI-TARS style `Thought:` / `Action:` model output.
- `VisualModel`: protocol for VLM adapters.
- `TaijiGatewayVisualModel`: OpenAI-compatible gateway adapter.
- `Operator`: protocol for screenshots and action execution.
- `DryRunOperator`: shadow-mode operator for safe validation.
- `PolicyEngine`: action allowlist and confirmation gate.
- `InMemoryConfirmationStore` / `JsonlConfirmationStore`: auditable pending action records.
- `GUIAgent`: the observe-think-act loop.
- `TaijiWindowsOperator`: optional Windows desktop operator.
- `Win32Backend`: dependency-free Win32 screenshot/input backend.

## First Integration Target

Use `DryRunOperator` for shadow mode:

```python
from aios.gui_agent import DryRunOperator, GUIAgent, PolicyEngine, TaijiGatewayVisualModel

agent = GUIAgent(
    operator=DryRunOperator(),
    model=TaijiGatewayVisualModel(model="ui-tars-compatible-vlm"),
    policy=PolicyEngine(shadow_mode=True),
)

run = agent.run("Open the browser and search for TaijiOS")
```

When real desktop control is ready, implement a TaijiOS-native `Operator` that
routes screenshot and input actions through TaijiOS permission gates instead of
calling OS automation libraries directly.

## Windows Operator

`TaijiWindowsOperator` maps approved UI-TARS actions to a backend. The default
backend uses Win32 APIs through `ctypes`, so it does not add Electron or Node
dependencies:

```python
from aios.gui_agent import GUIAgent, PolicyEngine, TaijiGatewayVisualModel, TaijiWindowsOperator

agent = GUIAgent(
    operator=TaijiWindowsOperator(),
    model=TaijiGatewayVisualModel(model="ui-tars-compatible-vlm"),
    policy=PolicyEngine(shadow_mode=True),
)
```

Keep `shadow_mode=True` until TaijiOS has a human confirmation UI. Tests inject
a fake backend, so running the test suite does not move the mouse or type text.

The run result exposes `pending_action` when a step stops for confirmation:

```python
from aios.gui_agent import JsonlConfirmationStore

agent = GUIAgent(
    operator=TaijiWindowsOperator(),
    model=TaijiGatewayVisualModel(model="ui-tars-compatible-vlm"),
    policy=PolicyEngine(shadow_mode=True),
    confirmation_store=JsonlConfirmationStore("runs/gui_agent/confirmations.jsonl"),
)

run = agent.run("Click the search box")
if run.status == "awaiting_confirmation":
    show_to_user(run.confirmation_id, run.pending_action)
    # Call this only after a TaijiOS UI or policy workflow approves it.
    agent.approve_confirmation(run.confirmation_id, actor="alice")
```

## Safety Defaults

- Shadow mode is on by default.
- High-risk actions require confirmation.
- Unknown actions are blocked.
- The agent emits `gui_agent.*` events when an event bus is supplied.

## Safe Demo

Run a deterministic dry-run demo without model keys or desktop control:

```bash
python examples/gui_agent_shadow_demo.py
```

It writes an append-only confirmation log to:

```text
examples/quickstart_output/gui_agent_confirmations.jsonl
```

## Shadow Mode Browser POC

Run the acceptance POC for the three safe tasks:

```bash
python examples/shadow_mode_browser_poc.py
```

It writes:

```text
runs/ops_check/shadow_mode_browser_poc_20260511/event_flow.jsonl
runs/ops_check/shadow_mode_browser_poc_20260511/summary.json
runs/ops_check/shadow_mode_browser_poc_20260511/shadow_mode_report.md
runs/ops_check/shadow_mode_browser_poc_20260511/confirmations.jsonl
```

The POC is deterministic and offline:

- Browser task uses a read-only in-memory page map.
- GUI task stops at policy review and records a pending confirmation.
- File task only lists files and writes a report in the run output directory.
- Summary flags remain `learning_only=true`, `judgment=false`,
  `paper_buy=false`, `trade=false`, `promote=false`.

Validate the generated artifacts independently:

```bash
python examples/validate_shadow_mode_browser_poc.py
```

The validator fails if the event flow is not parseable, secrets are present,
the summary enables live workflow/trading/promotion, the GUI action executed,
or file-read mutations are reported.

For CI and release checks, prefer the package gate because it regenerates and
validates all GUI-agent artifacts in one command:

```bash
python -m aios.gui_agent.ops_check_gate
python examples/validate_gui_agent_ops_check.py
```

The action safety rules are documented in
`docs/UI_TARS_POLICY_MATRIX.md`.

The optional Playwright adapter is read-only. It requires explicit
`allowed_hosts`, blocks mutating HTTP methods, and still does not allow
click/type/submit flows.

## Browser Read-Only Task Runner

Run the standalone browser read-only task:

```bash
python examples/browser_readonly_task.py
python examples/validate_browser_readonly_task.py
```

It writes:

```text
runs/ops_check/browser_readonly_task_20260511/event_flow.jsonl
runs/ops_check/browser_readonly_task_20260511/summary.json
runs/ops_check/browser_readonly_task_20260511/browser_readonly_report.md
```

The validator fails if artifacts are not parseable, if `live_workflow`,
`trade`, `promote`, `side_effects`, or `secret_detected` are enabled, or if
the event flow does not show read-only open/read completion.

The combined gate writes:

```text
runs/ops_check/gui_agent_ops_check_20260511/summary.json
runs/ops_check/gui_agent_ops_check_20260511/policy_matrix.json
```

The combined validator re-checks the summary, child gate statuses, child
validators, the machine-readable policy matrix, event-flow replay, ops-check
output locations, and secret redaction.

Event-flow replay loads `policy_matrix.json` and replays policy decision events
from the shadow and browser artifacts. It fails if an execution event has no
prior allowed policy decision, if desktop shadow actions do not stop for
confirmation, or if browser read-only actions report side effects.

The combined summary must keep these top-level safety fields:

```json
{
  "verdict": "gui_agent_ops_check_candidate",
  "learning_only": true,
  "judgment": false,
  "paper_buy": false,
  "trade": false,
  "promote": false,
  "live_workflow": false,
  "side_effects": false,
  "secret_detected": false
}
```
