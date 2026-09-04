"""Booking audit trail — who, when, and what for every write."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from app.agent.state import AgentState
from app.core.logging import get_logger
from app.core.observability import log_extra
from app.core.tracing import get_trace_id
from app.models.booking import BookingAuditAction, BookingAuditRecord, BookingRecord

_logger = get_logger("tools.booking_audit")


@dataclass(frozen=True)
class BookingAuditContext:
    """Caller identity attached to a booking write."""

    actor: str
    trace_id: str | None = None
    source: str = "agent"


def audit_context_from_state(state: AgentState) -> BookingAuditContext:
    """Build audit context from an agent session."""
    return BookingAuditContext(
        actor=state.conversation_id,
        trace_id=state.trace_id,
        source="agent",
    )


def audit_context_from_conversation(
    conversation_id: str,
    *,
    source: str = "mcp",
) -> BookingAuditContext:
    """Build audit context for direct MCP or API writes."""
    return BookingAuditContext(
        actor=conversation_id,
        trace_id=get_trace_id(),
        source=source,
    )


def audit_context_for_system(*, source: str = "system") -> BookingAuditContext:
    """Build audit context when no conversation is available."""
    return BookingAuditContext(
        actor=source,
        trace_id=get_trace_id(),
        source=source,
    )


def build_booking_audit_record(
    *,
    action: BookingAuditAction,
    record: BookingRecord,
    context: BookingAuditContext,
    detail: str | None = None,
    performed_at: str | None = None,
) -> BookingAuditRecord:
    """Create one audit record for a booking write."""
    from app.tools.booking_store import BookingStore

    return BookingAuditRecord(
        audit_id=uuid4().hex,
        action=action,
        booking_id=record.booking_id,
        conversation_id=record.conversation_id,
        flight_id=record.flight_id,
        passenger=record.passenger,
        actor=context.actor,
        trace_id=context.trace_id or get_trace_id(),
        performed_at=performed_at or BookingStore.utc_now_iso(),
        detail=detail,
    )


def log_booking_audit(audit: BookingAuditRecord) -> None:
    """Emit a structured audit log entry."""
    _logger.info(
        "booking_audit",
        extra=log_extra(
            event="booking_audit",
            trace_id=audit.trace_id,
            audit_id=audit.audit_id,
            action=audit.action.value,
            booking_id=audit.booking_id,
            conversation_id=audit.conversation_id,
            flight_id=audit.flight_id,
            passenger=audit.passenger,
            actor=audit.actor,
            performed_at=audit.performed_at,
            detail=audit.detail,
        ),
    )
