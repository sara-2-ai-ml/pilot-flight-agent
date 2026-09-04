"""Booking service tests — Phase 4.4 / 5.5."""

import pytest

from app.agent.state import AgentState
from app.models.booking import BookingStatus
from app.tools.booking_service import BookingService, mock_booking_id, parse_passenger_name
from app.tools.booking_store import BookingStore


@pytest.fixture
def booking_service(tmp_path) -> BookingService:
    store = BookingStore(str(tmp_path / "bookings.db"))
    return BookingService(store=store)


def test_parse_passenger_name_uses_default_without_hint() -> None:
    assert parse_passenger_name("Book this flight") == "Guest Passenger"


def test_parse_passenger_name_extracts_name() -> None:
    assert parse_passenger_name("Book flight for Ana Krasniqi") == "Ana Krasniqi"


def test_mock_booking_id_is_deterministic() -> None:
    first = mock_booking_id(conversation_id="conv1", flight_id="LH001")
    second = mock_booking_id(conversation_id="conv1", flight_id="LH001")

    assert first == second
    assert first.startswith("BK-")


def test_create_booking_updates_state_with_mock_record(booking_service: BookingService) -> None:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.user_message = "Book flight LH001 for Ana Krasniqi"
    state.flight_search.selected_option_id = "LH001"

    result = booking_service.create_booking(state)

    assert result.success is True
    assert state.booking.selected_flight == "LH001"
    assert state.booking.passenger == "Ana Krasniqi"
    assert state.booking.booking_id is not None
    assert state.booking.status == BookingStatus.PENDING
    assert "Created booking BK-" in result.message
    assert "pending confirmation" in result.message

    stored = booking_service._store.get(state.booking.booking_id)
    assert stored is not None
    assert stored.passenger == "Ana Krasniqi"
    assert stored.status == BookingStatus.PENDING


def test_create_booking_is_idempotent_for_same_conversation_and_flight(
    booking_service: BookingService,
) -> None:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.user_message = "Book flight LH001 for Ana Krasniqi"
    state.flight_search.selected_option_id = "LH001"

    first = booking_service.create_booking(state)
    second = booking_service.create_booking(state)

    assert first.success is True
    assert second.success is True
    assert "Returning existing booking" in second.message
    assert first.message != second.message


def test_create_booking_fails_without_selected_flight(booking_service: BookingService) -> None:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")

    result = booking_service.create_booking(state)

    assert result.success is False
    assert state.booking.status == BookingStatus.NONE
