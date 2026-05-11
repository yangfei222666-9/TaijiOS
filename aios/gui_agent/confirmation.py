"""Confirmation records for TaijiOS GUI action gates."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol

from .actions import Action
from .redaction import redact_secrets


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass(frozen=True)
class ConfirmationRequest:
    """A pending or decided request for a GUI action."""

    id: str
    instruction: str
    action: Action
    reason: str
    status: str = "pending"
    created_at: int = field(default_factory=_now_ms)
    decided_by: str | None = None
    decided_at: int | None = None
    execution_status: str | None = None
    metadata: dict = field(default_factory=dict)

    def to_dict(self, *, redact: bool = True) -> dict:
        data = asdict(self)
        return redact_secrets(data) if redact else data

    @classmethod
    def from_dict(cls, data: dict) -> "ConfirmationRequest":
        action_data = data.get("action") or {}
        action = Action(
            action_type=action_data.get("action_type", ""),
            inputs=action_data.get("inputs") or {},
            thought=action_data.get("thought", ""),
            reflection=action_data.get("reflection"),
        )
        return cls(
            id=data["id"],
            instruction=data.get("instruction", ""),
            action=action,
            reason=data.get("reason", ""),
            status=data.get("status", "pending"),
            created_at=data.get("created_at", _now_ms()),
            decided_by=data.get("decided_by"),
            decided_at=data.get("decided_at"),
            execution_status=data.get("execution_status"),
            metadata=data.get("metadata") or {},
        )


class ConfirmationStore(Protocol):
    """Store interface for GUI action confirmations."""

    def create(
        self,
        instruction: str,
        action: Action,
        reason: str,
        metadata: dict | None = None,
    ) -> ConfirmationRequest:
        """Create a pending confirmation request."""

    def get(self, confirmation_id: str) -> ConfirmationRequest | None:
        """Return the latest request state."""

    def approve(self, confirmation_id: str, actor: str) -> ConfirmationRequest:
        """Approve a pending request."""

    def reject(
        self,
        confirmation_id: str,
        actor: str,
        reason: str,
    ) -> ConfirmationRequest:
        """Reject a pending request."""

    def mark_executed(
        self,
        confirmation_id: str,
        execution_status: str,
    ) -> ConfirmationRequest:
        """Record execution completion for an approved request."""


class InMemoryConfirmationStore:
    """Simple confirmation store for tests and embedded flows."""

    def __init__(self):
        self._requests: dict[str, ConfirmationRequest] = {}

    def create(
        self,
        instruction: str,
        action: Action,
        reason: str,
        metadata: dict | None = None,
    ) -> ConfirmationRequest:
        request = ConfirmationRequest(
            id=str(uuid.uuid4()),
            instruction=instruction,
            action=action,
            reason=reason,
            metadata=metadata or {},
        )
        self._requests[request.id] = request
        return request

    def get(self, confirmation_id: str) -> ConfirmationRequest | None:
        return self._requests.get(confirmation_id)

    def approve(self, confirmation_id: str, actor: str) -> ConfirmationRequest:
        request = self._require_pending(confirmation_id)
        updated = self._replace(
            request,
            status="approved",
            decided_by=actor,
            decided_at=_now_ms(),
        )
        self._requests[confirmation_id] = updated
        return updated

    def reject(
        self,
        confirmation_id: str,
        actor: str,
        reason: str,
    ) -> ConfirmationRequest:
        request = self._require_pending(confirmation_id)
        updated = self._replace(
            request,
            status="rejected",
            decided_by=actor,
            decided_at=_now_ms(),
            metadata={**request.metadata, "reject_reason": reason},
        )
        self._requests[confirmation_id] = updated
        return updated

    def mark_executed(
        self,
        confirmation_id: str,
        execution_status: str,
    ) -> ConfirmationRequest:
        request = self._require(confirmation_id)
        if request.status not in {"approved", "executed"}:
            raise ValueError(f"confirmation is not approved: {request.status}")
        updated = self._replace(
            request,
            status="executed",
            execution_status=execution_status,
        )
        self._requests[confirmation_id] = updated
        return updated

    def _require(self, confirmation_id: str) -> ConfirmationRequest:
        request = self.get(confirmation_id)
        if request is None:
            raise KeyError(f"confirmation not found: {confirmation_id}")
        return request

    def _require_pending(self, confirmation_id: str) -> ConfirmationRequest:
        request = self._require(confirmation_id)
        if request.status != "pending":
            raise ValueError(f"confirmation is not pending: {request.status}")
        return request

    @staticmethod
    def _replace(request: ConfirmationRequest, **updates) -> ConfirmationRequest:
        data = request.to_dict(redact=False)
        data.update(updates)
        return ConfirmationRequest.from_dict(data)


class JsonlConfirmationStore(InMemoryConfirmationStore):
    """Append-only JSONL confirmation store with in-memory latest state."""

    def __init__(self, path: str | Path):
        super().__init__()
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._load()

    def create(
        self,
        instruction: str,
        action: Action,
        reason: str,
        metadata: dict | None = None,
    ) -> ConfirmationRequest:
        request = super().create(instruction, action, reason, metadata)
        self._append("created", request)
        return request

    def approve(self, confirmation_id: str, actor: str) -> ConfirmationRequest:
        request = super().approve(confirmation_id, actor)
        self._append("approved", request)
        return request

    def reject(
        self,
        confirmation_id: str,
        actor: str,
        reason: str,
    ) -> ConfirmationRequest:
        request = super().reject(confirmation_id, actor, reason)
        self._append("rejected", request)
        return request

    def mark_executed(
        self,
        confirmation_id: str,
        execution_status: str,
    ) -> ConfirmationRequest:
        request = super().mark_executed(confirmation_id, execution_status)
        self._append("executed", request)
        return request

    def _append(self, event_type: str, request: ConfirmationRequest) -> None:
        entry = {
            "event": event_type,
            "recorded_at": _now_ms(),
            "request": request.to_dict(),
        }
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _load(self) -> None:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    request = ConfirmationRequest.from_dict(entry["request"])
                except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                    continue
                self._requests[request.id] = request
