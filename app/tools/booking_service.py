"""Booking creation — shared logic for the booking worker."""

import hashlib
import re

from app.agent.state import AgentState
from app.agent.workers.base import WorkerResult
from app.config import Settings, get_settings
from app.core.errors import BookingUnavailableError
from app.core.idempotency import build_booking_idempotency_key
from app.models.booking import BookingRecord, BookingStatus
from app.tools.booking_audit import audit_context_from_state
from app.tools.booking_store import BookingStore

_PASSENGER_PATTERN = re.compile(
    r"\bfor\s+([A-Za-z]+(?:\s+[A-Za-z]+)?)\b",
    re.IGNORECASE,
)


def parse_passenger_name(message: str) -> str:
    """Extract a passenger name hint from the user message."""
    match = _PASSENGER_PATTERN.search(message)
    if match is None:
        return "Guest Passenger"
    return match.group(1).title()


def mock_booking_id(*, conversation_id: str, flight_id: str) -> str:
    """Deterministic booking id for local development and tests."""
    digest = hashlib.sha256(f"{conversation_id}:{flight_id}".encode()).hexdigest()[:8]
    return f"BK-{digest.upper()}"


class BookingService:
    """Create bookings against session state and the SQLite store."""

    def __init__(
        self,
        settings: Settings | None = None,
        store: BookingStore | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._store = store or BookingStore(self._settings.booking_db_path)

    def create_booking(self, state: AgentState) -> WorkerResult:
        flight_id = state.flight_search.selected_option_id
        if flight_id is None:
            return WorkerResult(
                message="No validated flight selected. Validate options before booking.",
                success=False,
            )

        passenger = parse_passenger_name(state.user_message)
        booking_id = mock_booking_id(
            conversation_id=state.conversation_id,
            flight_id=flight_id,
        )
        idempotency_key = build_booking_idempotency_key(
            conversation_id=state.conversation_id,
            flight_id=flight_id,
        )
        record = BookingRecord(
            booking_id=booking_id,
            conversation_id=state.conversation_id,
            flight_id=flight_id,
            passenger=passenger,
            status=BookingStatus.PENDING,
            created_at=BookingStore.utc_now_iso(),
        )
        try:
            stored, created = self._store.create_idempotent(
                record,
                idempotency_key=idempotency_key,
                audit_context=audit_context_from_state(state),
            )
        except Exception as exc:
            raise BookingUnavailableError() from exc
        passenger = stored.passenger
        booking_id = stored.booking_id

        state.booking.selected_flight = flight_id
        state.booking.passenger = passenger
        state.booking.booking_id = booking_id
        state.booking.status = BookingStatus.PENDING

        verb = "Created" if created else "Returning existing"
        return WorkerResult(
            message=(
                f"{verb} booking {booking_id} for flight {flight_id} "
                f"({passenger}, pending confirmation)."
            ),
            success=True,
        )
