"""Booking worker tests — Phase 4.4 / 6.1."""

from app.agent.state import AgentState
from app.agent.workers.booking_worker import BookingWorker
from app.config import Settings
from app.models.booking import BookingStatus
from app.tools.adapters.direct import DirectToolAdapter
from app.tools.booking_service import BookingService
from app.tools.booking_store import BookingStore


def test_booking_worker_create_booking_updates_state(tmp_path) -> None:
    store = BookingStore(str(tmp_path / "bookings.db"))
    adapter = DirectToolAdapter(
        settings=Settings(flight_api_use_mock=True),
        booking_service=BookingService(store=store),
    )
    worker = BookingWorker(adapter=adapter)
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.user_message = "Book for John Smith"
    state.flight_search.selected_option_id = "LH001"

    result = worker.execute("create_booking", state)

    assert result.success is True
    assert state.booking.booking_id is not None
    assert state.booking.status == BookingStatus.PENDING


def test_booking_worker_requires_validated_flight() -> None:
    worker = BookingWorker()
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")

    result = worker.execute("create_booking", state)

    assert result.success is False
