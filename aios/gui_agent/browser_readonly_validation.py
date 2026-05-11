"""Validation gate for browser read-only task artifacts."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from .redaction import contains_secret


REQUIRED_EVENT_TYPES = {
    "browser_readonly_task.started",
    "browser_readonly_task.policy_decision",
    "browser_readonly_task.open.requested",
    "browser_readonly_task.open.completed",
    "browser_readonly_task.read.completed",
    "browser_readonly_task.completed",
}


@dataclass
class BrowserReadonlyValidationResult:
    """Result of validating a browser read-only run directory."""

    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checked_files: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "errors": self.errors,
            "warnings": self.warnings,
            "checked_files": self.checked_files,
        }


def validate_browser_readonly_task(output_dir: str | Path) -> BrowserReadonlyValidationResult:
    """Validate event flow, summary and report for a browser read-only task."""
    output_dir = Path(output_dir)
    errors: list[str] = []
    warnings: list[str] = []
    checked_files: list[str] = []

    event_flow = output_dir / "event_flow.jsonl"
    summary_path = output_dir / "summary.json"
    report_path = output_dir / "browser_readonly_report.md"

    for path in (event_flow, summary_path, report_path):
        checked_files.append(str(path))
        if not path.exists():
            errors.append(f"missing artifact: {path.name}")

    events = _load_jsonl(event_flow, errors, "event_flow")
    summary = _load_json(summary_path, errors, "summary")
    report_text = report_path.read_text(encoding="utf-8") if report_path.exists() else ""

    _validate_summary(summary, errors)
    _validate_events(events, errors, set(summary.get("allowed_hosts") or []))
    _validate_report(report_text, errors, warnings)

    all_text = {
        "events": events,
        "summary": summary,
        "report": report_text,
    }
    if contains_secret(all_text):
        errors.append("secret-like value found in browser read-only artifacts")

    return BrowserReadonlyValidationResult(
        ok=not errors,
        errors=errors,
        warnings=warnings,
        checked_files=checked_files,
    )


def _load_json(path: Path, errors: list[str], label: str) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        errors.append(f"{label} is not valid JSON: {exc}")
        return {}


def _load_jsonl(path: Path, errors: list[str], label: str) -> list[dict]:
    if not path.exists():
        return []
    loaded: list[dict] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            loaded.append(json.loads(line))
        except json.JSONDecodeError as exc:
            errors.append(f"{label} line {line_number} is not valid JSON: {exc}")
    return loaded


def _validate_summary(summary: dict, errors: list[str]) -> None:
    expected_flags = {
        "verdict": "browser_readonly_candidate",
        "learning_only": True,
        "judgment": False,
        "paper_buy": False,
        "trade": False,
        "promote": False,
        "live_workflow": False,
        "side_effects": False,
        "secret_detected": False,
    }
    for key, expected in expected_flags.items():
        if summary.get(key) != expected:
            errors.append(f"summary.{key} expected {expected!r}, got {summary.get(key)!r}")

    if summary.get("status") != "completed":
        errors.append(f"summary.status expected 'completed', got {summary.get('status')!r}")

    allowed_hosts = set(summary.get("allowed_hosts") or [])
    if not allowed_hosts:
        errors.append("summary.allowed_hosts must not be empty")

    pages = summary.get("pages") or []
    if not pages:
        errors.append("summary.pages must not be empty")
        return

    for index, page in enumerate(pages):
        url = page.get("url")
        if url and not _url_allowed(url, allowed_hosts):
            errors.append(f"summary.pages[{index}].url is outside allowed_hosts")
        if page.get("status") != "completed":
            errors.append(f"summary.pages[{index}].status expected completed")
        if page.get("side_effect") is not False:
            errors.append(f"summary.pages[{index}].side_effect expected false")
        if page.get("text_chars", 0) <= 0:
            errors.append(f"summary.pages[{index}].text_chars must be positive")


def _validate_events(events: list[dict], errors: list[str], allowed_hosts: set[str]) -> None:
    event_types = {event.get("type") for event in events}
    missing = sorted(REQUIRED_EVENT_TYPES - event_types)
    if missing:
        errors.append(f"event_flow missing event types: {missing}")

    for event in events:
        payload = event.get("payload") or {}
        url = payload.get("url")
        if url and not _url_allowed(url, allowed_hosts):
            errors.append(f"{event.get('type')} url is outside allowed_hosts")
        metadata = payload.get("metadata") or {}
        metadata_url = metadata.get("url") if isinstance(metadata, dict) else None
        if metadata_url and not _url_allowed(metadata_url, allowed_hosts):
            errors.append(f"{event.get('type')} metadata.url is outside allowed_hosts")
        if event.get("type") == "browser_readonly_task.started":
            if payload.get("live_workflow") is not False:
                errors.append("browser_readonly_task.started live_workflow is not false")
            if not payload.get("allowed_hosts"):
                errors.append("browser_readonly_task.started missing allowed_hosts")
        if event.get("type") == "browser_readonly_task.policy_decision":
            if payload.get("allowed") is not True:
                errors.append("browser_readonly_task policy decision was not allowed")
            if payload.get("requires_confirmation") is not False:
                errors.append("browser_readonly_task unexpectedly required confirmation")
        if event.get("type") == "browser_readonly_task.open.requested":
            if payload.get("mode") != "read_only":
                errors.append("browser_readonly_task open request is not read_only")
        if event.get("type") == "browser_readonly_task.open.completed":
            if payload.get("side_effect") is not False:
                errors.append("browser_readonly_task open reported side_effect")
        if event.get("type") == "browser_readonly_task.read.completed":
            if payload.get("side_effect") is not False:
                errors.append("browser_readonly_task read reported side_effect")
        if event.get("type") == "browser_readonly_task.completed":
            if payload.get("side_effects") is not False:
                errors.append("browser_readonly_task completed with side_effects")


def _validate_report(report_text: str, errors: list[str], warnings: list[str]) -> None:
    if not report_text:
        return
    if "Side effects: false" not in report_text:
        errors.append("report does not state side effects are false")
    if "URL host allowlist is enforced" not in report_text:
        warnings.append("report does not mention URL host allowlist")


def _url_allowed(url: str, allowed_hosts: set[str]) -> bool:
    parsed = urlparse(url)
    return bool(parsed.scheme in {"http", "https"} and parsed.netloc in allowed_hosts)
