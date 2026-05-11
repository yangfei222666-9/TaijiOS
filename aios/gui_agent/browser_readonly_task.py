"""Browser read-only task runner for TaijiOS GUI agent workflows."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse

from .actions import Action
from .browser_adapter import BrowserActionResult, BrowserPage, ReadOnlyBrowserAdapter
from .playwright_browser_adapter import PlaywrightReadOnlyBrowserAdapter
from .policy import PolicyContext, PolicyEngine, PolicyRuleMatrix
from .redaction import contains_secret, redact_secrets


def now_ms() -> int:
    return int(time.time() * 1000)


class BrowserAdapter(Protocol):
    def execute(self, action: Action) -> BrowserActionResult:
        ...

    def close(self) -> None:
        ...


class EventFlowRecorder:
    """Append-only JSONL recorder for task event flow."""

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


@dataclass(frozen=True)
class BrowserReadonlyTask:
    """Configuration for a browser read-only task."""

    urls: tuple[str, ...]
    allowed_hosts: frozenset[str]
    instruction: str = "Read allowed pages and generate a report."
    adapter_kind: str = "offline"
    live_workflow: bool = False


@dataclass(frozen=True)
class BrowserReadonlyArtifacts:
    output_dir: Path
    event_flow: Path
    summary: Path
    report: Path


@dataclass
class BrowserReadonlyTaskRunner:
    """Run a read-only browser task and write auditable artifacts."""

    task: BrowserReadonlyTask
    output_dir: Path
    adapter: BrowserAdapter
    policy: PolicyEngine = field(init=False)

    def __post_init__(self) -> None:
        self.policy = PolicyEngine(
            shadow_mode=True,
            rule_matrix=PolicyRuleMatrix.default(),
            context=PolicyContext(
                surface="browser_readonly",
                read_only=True,
                live_workflow=self.task.live_workflow,
            ),
        )

    @classmethod
    def offline(
        cls,
        *,
        urls: tuple[str, ...],
        pages: dict[str, str],
        allowed_hosts: set[str] | frozenset[str],
        output_dir: str | Path,
        instruction: str = "Read allowed pages and generate a report.",
    ) -> "BrowserReadonlyTaskRunner":
        task = BrowserReadonlyTask(
            urls=urls,
            allowed_hosts=frozenset(allowed_hosts),
            instruction=instruction,
            adapter_kind="offline",
        )
        return cls(
            task=task,
            output_dir=Path(output_dir),
            adapter=ReadOnlyBrowserAdapter(pages, allowed_hosts=set(allowed_hosts)),
        )

    @classmethod
    def playwright(
        cls,
        *,
        urls: tuple[str, ...],
        allowed_hosts: set[str] | frozenset[str],
        output_dir: str | Path,
        instruction: str = "Read allowed pages and generate a report.",
        headless: bool = True,
        timeout_ms: int = 10_000,
    ) -> "BrowserReadonlyTaskRunner":
        task = BrowserReadonlyTask(
            urls=urls,
            allowed_hosts=frozenset(allowed_hosts),
            instruction=instruction,
            adapter_kind="playwright",
        )
        return cls(
            task=task,
            output_dir=Path(output_dir),
            adapter=PlaywrightReadOnlyBrowserAdapter(
                allowed_hosts=set(allowed_hosts),
                headless=headless,
                timeout_ms=timeout_ms,
            ),
        )

    def run(self) -> dict:
        artifacts = self._prepare_artifacts()
        recorder = EventFlowRecorder(artifacts.event_flow)
        recorder.emit("browser_readonly_task.started", "browser_readonly_task", {
            "instruction": self.task.instruction,
            "adapter_kind": self.task.adapter_kind,
            "allowed_hosts": sorted(self.task.allowed_hosts),
            "live_workflow": self.task.live_workflow,
        })

        pages: list[dict] = []
        status = "completed"
        errors: list[str] = []
        try:
            for url in self.task.urls:
                result = self._read_url(url, recorder)
                if result["status"] != "completed":
                    status = "blocked"
                    errors.append(result["reason"])
                pages.append(result)
        finally:
            close = getattr(self.adapter, "close", None)
            if close is not None:
                close()

        report_text = self._write_report(artifacts.report, pages, status, errors)
        summary = {
            "verdict": "browser_readonly_candidate",
            "learning_only": True,
            "judgment": False,
            "paper_buy": False,
            "trade": False,
            "promote": False,
            "live_workflow": self.task.live_workflow,
            "adapter_kind": self.task.adapter_kind,
            "status": status,
            "side_effects": False,
            "secret_detected": contains_secret({
                "events": recorder.events,
                "pages": pages,
                "report": report_text,
            }),
            "allowed_hosts": sorted(self.task.allowed_hosts),
            "pages": pages,
            "errors": errors,
            "artifacts": {
                "event_flow": str(artifacts.event_flow),
                "summary": str(artifacts.summary),
                "report": str(artifacts.report),
            },
        }
        summary = redact_secrets(summary)
        artifacts.summary.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        recorder.emit("browser_readonly_task.completed", "browser_readonly_task", {
            "status": summary["status"],
            "summary": str(artifacts.summary),
            "secret_detected": summary["secret_detected"],
            "side_effects": False,
        })
        return summary

    def _read_url(self, url: str, recorder: EventFlowRecorder) -> dict:
        if not self._url_allowed(url):
            reason = "url host is not in browser read-only allowlist"
            recorder.emit("browser_readonly_task.blocked", "browser_readonly_task", {
                "url": url,
                "reason": reason,
            })
            return self._blocked_result(url, reason)

        action = Action("navigate", {"url": url})
        decision = self.policy.evaluate(action)
        recorder.emit("browser_readonly_task.policy_decision", "policy", {
            "url": url,
            "surface": "browser_readonly",
            "action_type": action.action_type,
            "allowed": decision.allowed,
            "requires_confirmation": decision.requires_confirmation,
            "effect": decision.metadata.get("effect"),
            "reason": decision.reason,
        })
        if not decision.allowed:
            return self._blocked_result(url, decision.reason)

        recorder.emit("browser_readonly_task.open.requested", "browser", {
            "url": url,
            "adapter_kind": self.task.adapter_kind,
            "mode": "read_only",
        })
        open_result = self.adapter.execute(action)
        recorder.emit("browser_readonly_task.open.completed", "browser", {
            "url": url,
            "status": open_result.status,
            "reason": open_result.reason,
            "side_effect": open_result.side_effect,
            "metadata": open_result.metadata,
        })
        if open_result.status != "completed" or open_result.page is None:
            return self._blocked_result(url, open_result.reason, open_result)

        read_action = Action("read_current_page")
        read_decision = self.policy.evaluate(read_action)
        recorder.emit("browser_readonly_task.policy_decision", "policy", {
            "url": url,
            "surface": "browser_readonly",
            "action_type": read_action.action_type,
            "allowed": read_decision.allowed,
            "requires_confirmation": read_decision.requires_confirmation,
            "effect": read_decision.metadata.get("effect"),
            "reason": read_decision.reason,
        })
        if not read_decision.allowed:
            return self._blocked_result(url, read_decision.reason)

        read_result = self.adapter.execute(read_action)
        page = read_result.page or open_result.page
        recorder.emit("browser_readonly_task.read.completed", "browser", {
            "url": page.url,
            "title": page.title,
            "text_preview": page.text[:240],
            "status": read_result.status,
            "side_effect": read_result.side_effect,
        })
        return self._page_result(page, read_result)

    def _prepare_artifacts(self) -> BrowserReadonlyArtifacts:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        artifacts = BrowserReadonlyArtifacts(
            output_dir=self.output_dir,
            event_flow=self.output_dir / "event_flow.jsonl",
            summary=self.output_dir / "summary.json",
            report=self.output_dir / "browser_readonly_report.md",
        )
        for path in (artifacts.event_flow, artifacts.summary, artifacts.report):
            if path.exists():
                path.unlink()
        return artifacts

    def _url_allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        return bool(
            parsed.scheme in {"http", "https"}
            and parsed.netloc in self.task.allowed_hosts
        )

    def _blocked_result(
        self,
        url: str,
        reason: str,
        result: BrowserActionResult | None = None,
    ) -> dict:
        return {
            "status": "blocked",
            "url": redact_secrets(url),
            "reason": reason,
            "title": "",
            "text_chars": 0,
            "side_effect": False if result is None else result.side_effect,
            "network": (result.metadata or {}).get("network") if result else None,
        }

    def _page_result(self, page: BrowserPage, result: BrowserActionResult) -> dict:
        return {
            "status": result.status,
            "url": page.url,
            "title": page.title,
            "text_chars": len(page.text),
            "text_preview": page.text[:240],
            "side_effect": result.side_effect,
            "network": (result.metadata or {}).get("network"),
        }

    def _write_report(
        self,
        report_path: Path,
        pages: list[dict],
        status: str,
        errors: list[str],
    ) -> str:
        lines = [
            "# Browser Read-Only Task",
            "",
            f"Status: {status}",
            f"Adapter: {self.task.adapter_kind}",
            f"Live workflow: {str(self.task.live_workflow).lower()}",
            "Side effects: false",
            "",
            "## Pages",
            "",
        ]
        for page in pages:
            lines.extend([
                f"- URL: {page['url']}",
                f"  - Status: {page['status']}",
                f"  - Title: {page['title']}",
                f"  - Text chars: {page['text_chars']}",
            ])
            if page.get("reason"):
                lines.append(f"  - Reason: {page['reason']}")
        if errors:
            lines.extend(["", "## Errors", ""])
            lines.extend(f"- {error}" for error in errors)
        lines.extend([
            "",
            "## Guardrails",
            "",
            "- URL host allowlist is enforced before adapter execution.",
            "- Only read-only navigation and page text extraction are used.",
            "- Click, type, submit, checkout, trade, upload and download flows are not exposed.",
        ])
        report = redact_secrets("\n".join(lines) + "\n")
        report_path.write_text(report, encoding="utf-8")
        return report
