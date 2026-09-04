"""Safe user-facing response helpers."""

from __future__ import annotations

from app.config import Settings
from app.guardrails.output_guard import filter_user_response
from app.guardrails.pii import redact_pii


def safe_user_message(message: str, *, settings: Settings) -> str:
    """Return a filtered message safe to expose through the API."""
    guarded = filter_user_response(message, settings=settings).message
    return redact_pii(guarded, settings=settings).text
