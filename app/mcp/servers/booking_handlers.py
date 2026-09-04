"""Booking MCP tool handlers — testable logic separate from transport."""

from __future__ import annotations

from typing import Any

from app.config import Settings, get_settings
from app.core.idempotency import build_booking_idempotency_key
from app.models.booking import BookingRecord, BookingStatus
from app.tools.booking_audit import audit_context_from_conversation, audit_context_for_system
from app.tools.booking_service import mock_booking_id
from app.tools.booking_store import BookingStore


def _serialize_record(record: BookingRecord) -> dict[str, Any]:
    payload = record.model_dump()
    payload["status"] = record.status.value
    return payload


def create_booking_handler(
    *,
    conversation_id: str,
    flight_id: str,
    passenger: str,
    booking_id: str | None = None,
    idempotency_key: str | None = None,
    store: BookingStore | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Create a pending booking in the SQLite store."""
    resolved_store = store or BookingStore((settings or get_settings()).booking_db_path)
    resolved_booking_id = booking_id or mock_booking_id(
        conversation_id=conversation_id,
        flight_id=flight_id,
    )
    resolved_idempotency_key = idempotency_key or build_booking_idempotency_key(
        conversation_id=conversation_id,
        flight_id=flight_id,
    )
    record = BookingRecord(
        booking_id=resolved_booking_id,
        conversation_id=conversation_id,
        flight_id=flight_id,
        passenger=passenger,
        status=BookingStatus.PENDING,
        created_at=BookingStore.utc_now_iso(),
    )
    stored, created = resolved_store.create_idempotent(
        record,
        idempotency_key=resolved_idempotency_key,
        audit_context=audit_context_from_conversation(conversation_id),
    )
    return {
        "found": True,
        "idempotent_replay": not created,
        **_serialize_record(stored),
    }


def get_booking_handler(
    *,
    booking_id: str,
    store: BookingStore | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Fetch one booking by id."""
    resolved_store = store or BookingStore((settings or get_settings()).booking_db_path)
    record = resolved_store.get(booking_id)
    if record is None:
        return {"found": False, "booking_id": booking_id}
    return {"found": True, **_serialize_record(record)}


def cancel_booking_handler(
    *,
    booking_id: str,
    store: BookingStore | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Cancel one booking by id."""
    resolved_store = store or BookingStore((settings or get_settings()).booking_db_path)
    record = resolved_store.cancel(
        booking_id,
        audit_context=audit_context_for_system(source="mcp"),
    )
    if record is None:
        return {"found": False, "booking_id": booking_id, "cancelled": False}
    return {"found": True, "cancelled": True, **_serialize_record(record)}
