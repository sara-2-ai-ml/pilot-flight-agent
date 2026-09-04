"""Input guard — validation, length limits, and prompt injection checks."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Pattern

from app.config import Settings, get_settings

_CONTROL_CHAR_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

_INJECTION_PATTERNS: tuple[tuple[str, Pattern[str]], ...] = (
    (
        "ignore_instructions",
        re.compile(
            r"\bignore\s+(?:all\s+|previous\s+|prior\s+)?(?:instructions|rules|prompts)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "disregard_instructions",
        re.compile(
            r"\b(?:disregard|forget|override)\s+(?:your\s+|all\s+|previous\s+)?(?:instructions|rules|prompts)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "role_override",
        re.compile(
            r"\b(?:you are now|act as|pretend to be|pretend you are|switch to)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "system_prompt_leak",
        re.compile(
            r"\b(?:system prompt|developer message|hidden instructions|reveal (?:your )?prompt)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "jailbreak",
        re.compile(
            r"\b(?:jailbreak|dan mode|do anything now)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "role_marker_injection",
        re.compile(r"(?m)^(?:system|assistant|developer)\s*:", re.IGNORECASE),
    ),
)


class InputGuardError(ValueError):
    """Raised when user input fails guardrail validation."""


class PromptInjectionError(InputGuardError):
    """Raised when user input attempts prompt manipulation."""


@dataclass(frozen=True)
class PromptInjectionMatch:
    """One detected prompt injection heuristic."""

    rule: str
    excerpt: str


def normalize_user_input(message: str) -> str:
    """Trim surrounding whitespace from one user message."""
    return message.strip()


def detect_prompt_injection(message: str) -> PromptInjectionMatch | None:
    """Return the first prompt injection heuristic matched in a message."""
    for rule, pattern in _INJECTION_PATTERNS:
        match = pattern.search(message)
        if match is not None:
            start = max(match.start() - 20, 0)
            end = min(match.end() + 20, len(message))
            excerpt = message[start:end].strip()
            return PromptInjectionMatch(rule=rule, excerpt=excerpt)
    return None


def check_prompt_injection(
    message: str,
    *,
    settings: Settings | None = None,
) -> PromptInjectionMatch | None:
    """Block or warn on prompt injection attempts based on settings."""
    resolved = settings or get_settings()
    if not resolved.prompt_injection_guard_enabled:
        return None

    matched = detect_prompt_injection(message)
    if matched is None:
        return None

    if resolved.prompt_injection_block:
        raise PromptInjectionError(
            "Message contains disallowed prompt manipulation and was blocked.",
        )

    return matched


def validate_user_message(
    message: str,
    *,
    settings: Settings | None = None,
) -> str:
    """Validate and normalize a user message before it reaches the agent loop."""
    resolved = settings or get_settings()
    normalized = normalize_user_input(message)

    if len(normalized) < resolved.min_user_message_length:
        raise InputGuardError("Message must not be empty.")

    if len(normalized) > resolved.max_user_message_length:
        raise InputGuardError(
            f"Message exceeds the maximum length of {resolved.max_user_message_length} characters.",
        )

    if _CONTROL_CHAR_PATTERN.search(normalized):
        raise InputGuardError("Message contains invalid control characters.")

    check_prompt_injection(normalized, settings=resolved)

    return normalized
