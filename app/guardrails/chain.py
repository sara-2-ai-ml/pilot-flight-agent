"""Guard chain — orchestrates security checks before and after the agent loop.

Inbound order (API boundary, before ``run_chat``):

1. **Per-IP rate limit** — ``RateLimitMiddleware`` on ``/chat`` and ``/approvals/*``
2. **Input validation** — trim, length, control characters
3. **Prompt injection detection** — heuristic block/warn
4. **Per-conversation rate limit** — handler-level bucket

Outbound order (after agent loop, before HTTP response):

1. **Output guard** — block tracebacks/SQL dumps, redact secrets and paths
2. **PII redaction** — mask emails and phone numbers

Structured logs apply PII redaction in ``StructuredFormatter`` independently of API
responses so log lines never leak contact details even when handlers skip outbound
guards.
"""

from __future__ import annotations

from app.api.rate_limit_helpers import enforce_conversation_rate_limit
from app.api.response_helpers import safe_user_message
from app.config import Settings
from app.guardrails.input_guard import validate_user_message

__all__ = (
    "run_inbound_approval_guards",
    "run_inbound_chat_guards",
    "run_outbound_guards",
)


def run_inbound_chat_guards(
    message: str,
    conversation_id: str | None,
    *,
    settings: Settings,
) -> str:
    """Run inbound guards for ``POST /chat`` before the agent loop."""
    validated = validate_user_message(message, settings=settings)
    enforce_conversation_rate_limit(conversation_id, settings=settings)
    return validated


def run_inbound_approval_guards(
    conversation_id: str,
    *,
    settings: Settings,
) -> None:
    """Run inbound guards for approval endpoints before side effects."""
    enforce_conversation_rate_limit(conversation_id, settings=settings)


def run_outbound_guards(message: str, *, settings: Settings) -> str:
    """Run outbound guards on agent output before returning to the client."""
    return safe_user_message(message, settings=settings)
