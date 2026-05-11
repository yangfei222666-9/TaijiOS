"""Validation gate for UI-TARS shadow-mode POC artifacts."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .redaction import contains_secret


REQUIRED_EVENT_TYPES = {
    "poc.started",
    "browser.open.requested",
    "browser.read.completed",
    "gui_shadow.started",
    "gui_shadow.policy_decision",
    "file_read.requested",
    "file_read.completed",
    "poc.completed",
}


@dataclass
class ValidationResult:
    """Result of validating a shadow-mode POC run directory."""

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


def validate_shadow_mode_poc(output_dir: str | Path) -> ValidationResult:
    """Validate event flow, summary, report and confirmation artifacts."""
    output_dir = Path(output_dir)
    errors: list[str] = []
    warnings: list[str] = []
    checked_files: list[str] = []

    event_flow = output_dir / "event_flow.jsonl"
    summary_path = output_dir / "summary.json"
    report_path = output_dir / "shadow_mode_report.md"
    confirmations_path = output_dir / "confirmations.jsonl"

    for path in (event_flow, summary_path, report_path, confirmations_path):
        checked_files.append(str(path))
        if not path.exists():
            errors.append(f"missing artifact: {path.name}")

    events = _load_jsonl(event_flow, errors, "event_flow")
    confirmations = _load_jsonl(confirmations_path, errors, "confirmations")
    summary = _load_json(summary_path, errors, "summary")
    report_text = report_path.read_text(encoding="utf-8") if report_path.exists() else ""

    _validate_summary(summary, errors)
    _validate_events(events, errors)
    _validate_confirmations(confirmations, errors)

    all_text = {
        "events": events,
        "confirmations": confirmations,
        "summary": summary,
        "report": report_text,
    }
    if contains_secret(all_text):
        errors.append("secret-like value found in artifacts")

    if "Raw screenshots are not embedded" not in report_text:
        warnings.append("report does not explicitly mention screenshot handling")

    return ValidationResult(ok=not errors, errors=errors, warnings=warnings, checked_files=checked_files)


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
        "verdict": "review_only_candidate",
        "learning_only": True,
        "judgment": False,
        "paper_buy": False,
        "trade": False,
        "promote": False,
        "live_workflow": False,
        "secret_detected": False,
    }
    for key, expected in expected_flags.items():
        if summary.get(key) != expected:
            errors.append(f"summary.{key} expected {expected!r}, got {summary.get(key)!r}")

    tasks = summary.get("tasks") or {}
    gui = tasks.get("local_gui_shadow") or {}
    files = tasks.get("file_readonly") or {}
    browser = tasks.get("browser_readonly") or {}

    if browser.get("status") != "completed":
        errors.append("browser_readonly did not complete")
    if gui.get("status") != "awaiting_confirmation":
        errors.append("local_gui_shadow did not stop for confirmation")
    if gui.get("executed") is not False:
        errors.append("local_gui_shadow executed an action")
    if files.get("mutations") != []:
        errors.append("file_readonly reported mutations")


def _validate_events(events: list[dict], errors: list[str]) -> None:
    event_types = {event.get("type") for event in events}
    missing = sorted(REQUIRED_EVENT_TYPES - event_types)
    if missing:
        errors.append(f"event_flow missing event types: {missing}")

    for event in events:
        payload = event.get("payload") or {}
        if event.get("type") == "browser.open.requested":
            if payload.get("mode") != "read_only":
                errors.append("browser.open.requested is not read_only")
            if payload.get("network") is not False:
                errors.append("browser.open.requested used network")
        if event.get("type") == "gui_shadow.policy_decision":
            if payload.get("executed") is not False:
                errors.append("gui shadow policy event executed action")
            if not payload.get("confirmation_id"):
                errors.append("gui shadow policy event has no confirmation_id")
        if event.get("type") == "file_read.requested":
            if payload.get("mode") != "read_only":
                errors.append("file_read.requested is not read_only")
            forbidden = set(payload.get("forbidden") or [])
            if not {"delete", "overwrite", "move"}.issubset(forbidden):
                errors.append("file_read.requested missing forbidden mutation list")


def _validate_confirmations(confirmations: list[dict], errors: list[str]) -> None:
    if not confirmations:
        errors.append("no confirmation records found")
        return

    latest_by_id: dict[str, dict] = {}
    for entry in confirmations:
        request = entry.get("request") or {}
        request_id = request.get("id")
        if request_id:
            latest_by_id[request_id] = request

    pending_or_executed = [
        request
        for request in latest_by_id.values()
        if request.get("status") in {"pending", "executed"}
    ]
    if not pending_or_executed:
        errors.append("no pending or executed confirmation request found")

    for request in latest_by_id.values():
        action = request.get("action") or {}
        if action.get("action_type") in {"delete_file", "move_file", "trade", "buy"}:
            errors.append(f"forbidden confirmation action: {action.get('action_type')}")
