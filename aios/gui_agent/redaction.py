"""Redaction helpers for GUI agent artifacts."""

from __future__ import annotations

import json
import re
from typing import Any


SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"(?i)(api[_-]?key|token|secret)\s*[:=]\s*[A-Za-z0-9_.-]{8,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9_.-]{8,}"),
]


def redact_secrets(value: Any):
    """Recursively redact obvious secret-looking strings."""
    if isinstance(value, str):
        redacted = value
        for pattern in SECRET_PATTERNS:
            redacted = pattern.sub("[REDACTED_SECRET]", redacted)
        return redacted
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    if isinstance(value, tuple):
        return [redact_secrets(item) for item in value]
    if isinstance(value, dict):
        return {key: redact_secrets(item) for key, item in value.items()}
    return value


def contains_secret(value: Any) -> bool:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return any(pattern.search(text) for pattern in SECRET_PATTERNS)
