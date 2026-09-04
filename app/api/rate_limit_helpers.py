"""Shared rate-limit enforcement for API handlers."""

from __future__ import annotations

from fastapi import HTTPException

from app.config import Settings, get_settings
from app.guardrails.rate_limit import check_conversation_rate_limit


def enforce_conversation_rate_limit(
    conversation_id: str | None,
    *,
    settings: Settings | None = None,
) -> None:
    """Raise HTTP 429 when a conversation exceeds its request budget."""
    if not conversation_id:
        return

    result = check_conversation_rate_limit(conversation_id, settings=settings or get_settings())
    if result.allowed:
        return

    retry_after = result.retry_after_seconds or 1
    raise HTTPException(
        status_code=429,
        detail="Too many requests for this conversation. Please try again later.",
        headers={"Retry-After": str(retry_after)},
    )
