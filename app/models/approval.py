"""Human approval payload models — Phase 7.5."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ApprovalRoute(BaseModel):
    """Route context shown before booking confirmation."""

    origin: str = Field(min_length=3, max_length=3)
    destination: str = Field(min_length=3, max_length=3)
    date: str = Field(min_length=1)
    origin_city: str | None = None
    destination_city: str | None = None


class ApprovalFlight(BaseModel):
    """Selected flight details shown before booking confirmation."""

    id: str = Field(min_length=1)
    carrier: str = Field(min_length=1)
    origin: str = Field(min_length=3, max_length=3)
    destination: str = Field(min_length=3, max_length=3)
    departure_time: str = Field(min_length=1)
    arrival_time: str = Field(min_length=1)


class BookingApprovalPayload(BaseModel):
    """Structured approval request for create_booking."""

    action: str = "create_booking"
    step_id: str = Field(min_length=1)
    worker: str = Field(min_length=1)
    conversation_id: str = Field(min_length=1)
    passenger: str = Field(min_length=1)
    route: ApprovalRoute
    flight: ApprovalFlight

    @property
    def flight_id(self) -> str:
        return self.flight.id


class ApprovalPendingResponse(BaseModel):
    """Pending approval lookup response."""

    trace_id: str
    conversation_id: str
    pending_approval: BookingApprovalPayload | None = None
