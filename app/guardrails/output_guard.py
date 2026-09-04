"""Output guard — filter tool and LLM output before user response."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Pattern

from app.config import Settings, get_settings

SAFE_OUTPUT_FALLBACK = (
    "I couldn't share the full response safely. Please try again or rephrase your request."
)

_TRACEBACK_PATTERN = re.compile(r"Traceback \(most recent call last\):", re.IGNORECASE)
_EXCEPTION_LINE_PATTERN = re.compile(r"^\s*(?:File|line)\s+", re.IGNORECASE | re.MULTILINE)
_INTERNAL_PATH_PATTERN = re.compile(
    r"(?:[A-Za-z]:\\|/)(?:[\w.-]+[/\\])+[\w.-]+\.(?:py|env|json|db|sqlite)",
)
_API_KEY_PATTERN = re.compile(
    r"\b(?:sk-[A-Za-z0-9]{20,}|Bearer\s+[A-Za-z0-9._-]{10,})\b",
)
_ENV_ASSIGNMENT_PATTERN = re.compile(
    r"\b(?:ANTHROPIC|FLIGHT|API|SECRET|TOKEN|PASSWORD|KEY)[A-Z0-9_]*\s*=\s*\S+",
    re.IGNORECASE,
)
_SQL_DUMP_PATTERN = re.compile(
    r"\b(?:SELECT|INSERT|UPDATE|DELETE)\s+.+\s+FROM\s+\w+",
    re.IGNORECASE,
)

_REDACTION_RULES: tuple[tuple[str, Pattern[str], str], ...] = (
    ("api_key", _API_KEY_PATTERN, "[REDACTED_SECRET]"),
    ("env_assignment", _ENV_ASSIGNMENT_PATTERN, "[REDACTED_CONFIG]"),
    ("internal_path", _INTERNAL_PATH_PATTERN, "[REDACTED_PATH]"),
)


@dataclass(frozen=True)
class OutputGuardResult:
    """Outcome of filtering one user-facing message."""

    message: str
    sanitized: bool
    blocked: bool
    reasons: tuple[str, ...] = ()


def _apply_redactions(message: str) -> tuple[str, tuple[str, ...]]:
    filtered = message
    reasons: list[str] = []
    for rule_name, pattern, replacement in _REDACTION_RULES:
        if pattern.search(filtered):
            filtered = pattern.sub(replacement, filtered)
            reasons.append(rule_name)
    return filtered, tuple(reasons)


def filter_user_response(
    message: str,
    *,
    settings: Settings | None = None,
) -> OutputGuardResult:
    """Filter unsafe tool/LLM output before returning it to the user."""
    resolved = settings or get_settings()
    if not resolved.output_guard_enabled:
        return OutputGuardResult(message=message, sanitized=False, blocked=False)

    if _TRACEBACK_PATTERN.search(message) or _EXCEPTION_LINE_PATTERN.search(message):
        return OutputGuardResult(
            message=SAFE_OUTPUT_FALLBACK,
            sanitized=True,
            blocked=True,
            reasons=("traceback",),
        )

    if _SQL_DUMP_PATTERN.search(message):
        return OutputGuardResult(
            message=SAFE_OUTPUT_FALLBACK,
            sanitized=True,
            blocked=True,
            reasons=("sql_dump",),
        )

    filtered, reasons = _apply_redactions(message)
    if reasons:
        return OutputGuardResult(
            message=filtered,
            sanitized=True,
            blocked=False,
            reasons=reasons,
        )

    return OutputGuardResult(message=message, sanitized=False, blocked=False)
