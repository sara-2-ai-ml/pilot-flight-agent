"""Booking domain models — passenger, booking record, status."""

from enum import Enum

from pydantic import BaseModel, Field


class BookingStatus(str, Enum):
    NONE = "none"
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


class BookingAuditAction(str, Enum):
    CREATE = "create"
    CANCEL = "cancel"


class BookingAuditRecord(BaseModel):
    """Immutable audit entry for one booking write operation."""

    audit_id: str = Field(min_length=1)
    action: BookingAuditAction
    booking_id: str = Field(min_length=1)
    conversation_id: str | None = None
    flight_id: str | None = None
    passenger: str | None = None
    actor: str = Field(min_length=1, description="Who initiated the write")
    trace_id: str | None = None
    performed_at: str = Field(min_length=1)
    detail: str | None = None


class BookingRecord(BaseModel):
    """Persisted booking row."""

    booking_id: str = Field(min_length=1)
    conversation_id: str = Field(min_length=1)
    flight_id: str = Field(min_length=1)
    passenger: str = Field(min_length=1)
    status: BookingStatus = BookingStatus.PENDING
    created_at: str = Field(min_length=1)
    idempotency_key: str | None = None


class BookingState(BaseModel):
    selected_flight: str | None = None
    passenger: str | None = None
    booking_id: str | None = None
    status: BookingStatus = BookingStatus.NONE
