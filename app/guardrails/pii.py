"""PII detection and redaction."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Pattern

from app.config import Settings, get_settings

REDACTED_EMAIL = "[REDACTED_EMAIL]"
REDACTED_PHONE = "[REDACTED_PHONE]"

_EMAIL_PATTERN = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
)
_PHONE_PATTERNS: tuple[Pattern[str], ...] = (
    re.compile(r"(?<!\d)\+\d{10,14}(?!\d)"),
    re.compile(r"(?<!\d)\+\d{1,3}(?:[\s.-]\d{2,4}){2,4}(?!\d)"),
    re.compile(r"(?<!\d)\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}(?!\d)"),
)

_PII_RULES: tuple[tuple[str, Pattern[str] | tuple[Pattern[str], ...], str], ...] = (
    ("email", _EMAIL_PATTERN, REDACTED_EMAIL),
    ("phone", _PHONE_PATTERNS, REDACTED_PHONE),
)


@dataclass(frozen=True)
class PiiRedactionResult:
    """Outcome of redacting PII from one text blob."""

    text: str
    redacted: bool
    kinds: tuple[str, ...] = ()


def redact_pii(
    text: str,
    *,
    settings: Settings | None = None,
) -> PiiRedactionResult:
    """Redact email addresses and phone numbers from text."""
    resolved = settings or get_settings()
    if not resolved.pii_redaction_enabled:
        return PiiRedactionResult(text=text, redacted=False)

    filtered = text
    kinds: list[str] = []
    for kind, pattern, replacement in _PII_RULES:
        patterns = pattern if isinstance(pattern, tuple) else (pattern,)
        matched = False
        for item in patterns:
            if item.search(filtered):
                filtered = item.sub(replacement, filtered)
                matched = True
        if matched:
            kinds.append(kind)

    return PiiRedactionResult(
        text=filtered,
        redacted=bool(kinds),
        kinds=tuple(kinds),
    )


_PII_REDACT_SKIP_KEYS = frozenset(
    {
        "trace_id",
        "span_id",
        "audit_id",
        "conversation_id",
        "booking_id",
    }
)


def redact_pii_in_mapping(
    payload: dict[str, object],
    *,
    settings: Settings | None = None,
) -> dict[str, object]:
    """Redact PII from string values in a log or API payload mapping."""
    resolved = settings or get_settings()
    if not resolved.pii_redaction_enabled:
        return payload

    redacted: dict[str, object] = {}
    for key, value in payload.items():
        if isinstance(value, str) and key not in _PII_REDACT_SKIP_KEYS:
            redacted[key] = redact_pii(value, settings=resolved).text
        else:
            redacted[key] = value
    return redacted
