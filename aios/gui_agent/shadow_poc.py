"""Deterministic shadow-mode GUI Agent POC for TaijiOS.

This module produces auditable artifacts without live browser control, desktop
input, file mutation outside the output directory, or network access.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from .actions import Action
from .agent import GUIAgent
from .browser_adapter import ReadOnlyBrowserAdapter
from .confirmation import JsonlConfirmationStore
from .models import ModelResult
from .operators import DryRunOperator
from .policy import PolicyContext, PolicyEngine, PolicyRuleMatrix
from .redaction import contains_secret, redact_secrets

DEMO_HEADER_SECRET = "api" + "_key=" + "sk-demo-" + "secret-00000000"


def now_ms() -> int:
    return int(time.time() * 1000)


class EventFlowRecorder:
    """Append-only JSONL recorder for POC event flow."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.events: list[dict] = []

    def emit(self, event_type: str, source: str, payload: dict | None = None) -> dict:
        event = {
            "id": str(uuid.uuid4()),
            "ts": now_ms(),
            "type": event_type,
            "source": source,
            "payload": redact_secrets(payload or {}),
        }
        self.events.append(event)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
        return event


class ScriptedShadowModel:
    """Deterministic UI-TARS style model for local GUI shadow tasks."""

    def invoke(self, instruction, screenshot, history, previous_response_id=None):
        return ModelResult(
            prediction=(
                "Thought: I would click the settings search box, but TaijiOS "
                "must review the action first.\n"
                "Action: click(start_box='[120, 120, 180, 180]')"
            )
        )


@dataclass
class POCArtifacts:
    output_dir: Path
    event_flow: Path
    summary: Path
    report: Path
    confirmations: Path


@dataclass
class ShadowModeBrowserPOC:
    """Runs the three requested POC tasks and writes review artifacts."""

    output_dir: Path
    readonly_root: Path
    browser_pages: dict[str, str] = field(default_factory=dict)

    def run(self) -> dict:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        artifacts = POCArtifacts(
            output_dir=self.output_dir,
            event_flow=self.output_dir / "event_flow.jsonl",
            summary=self.output_dir / "summary.json",
            report=self.output_dir / "shadow_mode_report.md",
            confirmations=self.output_dir / "confirmations.jsonl",
        )
        for path in (
            artifacts.event_flow,
            artifacts.summary,
            artifacts.report,
            artifacts.confirmations,
        ):
            if path.exists():
                path.unlink()

        recorder = EventFlowRecorder(artifacts.event_flow)
        recorder.emit("poc.started", "shadow_mode_browser_poc", {
            "verdict": "review_only_candidate",
            "live_workflow": False,
            "trade": False,
            "paper_buy": False,
        })

        browser_result = self._run_browser_readonly(recorder)
        gui_result = self._run_gui_shadow(recorder, artifacts.confirmations)
        file_result = self._run_file_readonly(recorder)
        report_text = self._write_report(artifacts.report, browser_result, gui_result, file_result)

        summary = {
            "verdict": "review_only_candidate",
            "learning_only": True,
            "judgment": False,
            "paper_buy": False,
            "trade": False,
            "promote": False,
            "live_workflow": False,
            "secret_detected": contains_secret({
                "events": recorder.events,
                "report": report_text,
            }),
            "tasks": {
                "browser_readonly": browser_result,
                "local_gui_shadow": gui_result,
                "file_readonly": file_result,
            },
            "artifacts": {
                "event_flow": str(artifacts.event_flow),
                "summary": str(artifacts.summary),
                "report": str(artifacts.report),
                "confirmations": str(artifacts.confirmations),
            },
        }
        summary = redact_secrets(summary)
        with artifacts.summary.open("w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

        recorder.emit("poc.completed", "shadow_mode_browser_poc", {
            "summary": str(artifacts.summary),
            "secret_detected": summary["secret_detected"],
        })
        return summary

    def _run_browser_readonly(self, recorder: EventFlowRecorder) -> dict:
        url = "https://example.taijios.local/ui-tars-review"
        pages = self.browser_pages or {
            url: f"""
            <html>
              <head><title>UI-TARS TaijiOS review</title></head>
              <body>
                <h1>UI-TARS candidate</h1>
                <p>Use only as a GUI action loop candidate.</p>
                <p>Production requires policy review, shadow mode and event replay.</p>
                <p>Do not expose {DEMO_HEADER_SECRET} in reports.</p>
              </body>
            </html>
            """,
        }
        browser = ReadOnlyBrowserAdapter(pages)
        policy = PolicyEngine(
            shadow_mode=True,
            rule_matrix=PolicyRuleMatrix.default(),
            context=PolicyContext(surface="browser_readonly", read_only=True),
        )
        navigate = Action("navigate", {"url": url})
        navigate_decision = policy.evaluate(navigate)
        recorder.emit("browser.policy_decision", "policy", {
            "url": url,
            "surface": "browser_readonly",
            "action_type": navigate.action_type,
            "allowed": navigate_decision.allowed,
            "requires_confirmation": navigate_decision.requires_confirmation,
            "effect": navigate_decision.metadata.get("effect"),
            "reason": navigate_decision.reason,
        })
        if not navigate_decision.allowed:
            raise RuntimeError(navigate_decision.reason)

        recorder.emit("browser.open.requested", "readonly_browser", {
            "url": url,
            "mode": "read_only",
            "network": False,
        })
        browser_result = browser.open(url)
        if browser_result.status != "completed" or browser_result.page is None:
            raise RuntimeError(browser_result.reason)
        page = browser_result.page
        read_action = Action("read_current_page")
        read_decision = policy.evaluate(read_action)
        recorder.emit("browser.policy_decision", "policy", {
            "url": url,
            "surface": "browser_readonly",
            "action_type": read_action.action_type,
            "allowed": read_decision.allowed,
            "requires_confirmation": read_decision.requires_confirmation,
            "effect": read_decision.metadata.get("effect"),
            "reason": read_decision.reason,
        })
        if not read_decision.allowed:
            raise RuntimeError(read_decision.reason)

        recorder.emit("browser.read.completed", "readonly_browser", {
            "url": page.url,
            "title": page.title,
            "text_preview": page.text[:240],
            "side_effect": False,
        })
        return {
            "status": "completed",
            "url": page.url,
            "title": page.title,
            "text_chars": len(page.text),
            "report": "UI-TARS is useful only as a controlled GUI action loop candidate.",
        }

    def _run_gui_shadow(self, recorder: EventFlowRecorder, confirmations_path: Path) -> dict:
        confirmation_store = JsonlConfirmationStore(confirmations_path)
        agent = GUIAgent(
            operator=DryRunOperator(),
            model=ScriptedShadowModel(),
            policy=PolicyEngine(
                shadow_mode=True,
                rule_matrix=PolicyRuleMatrix.default(),
                context=PolicyContext(surface="desktop_shadow"),
            ),
            confirmation_store=confirmation_store,
        )
        recorder.emit("gui_shadow.started", "gui_agent", {
            "screenshot_ref": "dry-run://screenshot/current",
            "raw_screenshot_embedded": False,
        })
        run = agent.run("Suggest the next click but do not execute it")
        action = run.pending_action
        decision = run.steps[-1].decisions[-1] if run.steps and run.steps[-1].decisions else None
        recorder.emit("gui_shadow.policy_decision", "gui_agent", {
            "status": run.status,
            "confirmation_id": run.confirmation_id,
            "surface": "desktop_shadow",
            "action_type": action.action_type if action else None,
            "inputs": action.inputs if action else {},
            "allowed": decision.allowed if decision else None,
            "requires_confirmation": decision.requires_confirmation if decision else None,
            "effect": decision.metadata.get("effect") if decision else None,
            "reason": decision.reason if decision else None,
            "executed": False,
        })
        return {
            "status": run.status,
            "confirmation_id": run.confirmation_id,
            "pending_action": action.action_type if action else None,
            "executed": False,
        }

    def _run_file_readonly(self, recorder: EventFlowRecorder) -> dict:
        root = self.readonly_root.resolve()
        recorder.emit("file_read.requested", "readonly_files", {
            "root": str(root),
            "mode": "read_only",
            "forbidden": ["delete", "overwrite", "move"],
        })
        files = list(self._iter_files(root, max_items=25))
        recorder.emit("file_read.completed", "readonly_files", {
            "root": str(root),
            "file_count": len(files),
            "files": files,
        })
        return {
            "status": "completed",
            "root": str(root),
            "file_count": len(files),
            "files": files[:10],
            "mutations": [],
        }

    def _iter_files(self, root: Path, max_items: int) -> Iterable[str]:
        count = 0
        for path in sorted(root.rglob("*")):
            if count >= max_items:
                break
            if path.is_file():
                yield str(path.relative_to(root))
                count += 1

    def _write_report(
        self,
        report_path: Path,
        browser_result: dict,
        gui_result: dict,
        file_result: dict,
    ) -> str:
        report = f"""# Shadow Mode Browser POC

Verdict: review_only_candidate

## Browser Read-Only

- Status: {browser_result['status']}
- URL: {browser_result['url']}
- Finding: {browser_result['report']}

## Local GUI Shadow

- Status: {gui_result['status']}
- Confirmation ID: {gui_result['confirmation_id']}
- Pending action: {gui_result['pending_action']}
- Executed: {gui_result['executed']}

## File Read-Only

- Status: {file_result['status']}
- Root: {file_result['root']}
- File count sampled: {file_result['file_count']}
- Mutations: {file_result['mutations']}

## Guardrails

- No live workflow.
- No transaction permission.
- No delete, overwrite or move permission.
- Raw screenshots are not embedded; only screenshot references are logged.
"""
        report = redact_secrets(report)
        report_path.write_text(report, encoding="utf-8")
        return report
