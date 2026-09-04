"""Domain state integration tests — Phase 5.7."""

from app.agent.loop import run_chat
from app.agent.state import AgentState, InMemoryStateStore, get_state_store
from app.models.booking import BookingStatus
from app.models.flight import FlightOption, FlightStatusInfo
from app.models.planning import PlanStatus
from app.tools.flight_client import mock_flight_options


def test_run_chat_populates_flight_search_results_after_full_plan() -> None:
    store = InMemoryStateStore()

    state, message = run_chat(
        user_message="Book flights TIA to FRA on 2025-09-15",
        trace_id="trace1",
        conversation_id="conv-domain-1",
        store=store,
    )

    assert state.plan.status == PlanStatus.IN_PROGRESS
    assert "Found 3 mock flights from TIA to FRA" in message
    assert state.flight_search.origin == "TIA"
    assert state.flight_search.destination == "FRA"
    assert state.flight_search.date == "2025-09-15"
    assert len(state.flight_search.results) == 3
    assert all(isinstance(option, FlightOption) for option in state.flight_search.results)
    assert state.flight_search.selected_option_id == "LH001"


def test_run_chat_populates_booking_state_after_full_plan() -> None:
    store = InMemoryStateStore()

    state, message = run_chat(
        user_message="Book flights TIA to FRA on 2025-09-15",
        trace_id="trace1",
        conversation_id="conv-domain-2",
        store=store,
    )

    assert "Booking approval required" in message
    assert state.pending_approval is not None
    assert state.pending_approval["flight"]["id"] == "LH001"
    assert state.booking.booking_id is None
    assert state.booking.status == BookingStatus.NONE


def test_persisted_state_keeps_flight_search_and_booking() -> None:
    store = InMemoryStateStore()

    state, _ = run_chat(
        user_message="Book flights TIA to FRA on 2025-09-15",
        trace_id="trace1",
        conversation_id="conv-domain-3",
        store=store,
    )
    follow_up, _ = run_chat(
        user_message="Any updates?",
        trace_id="trace2",
        conversation_id="conv-domain-3",
        store=store,
    )

    persisted = store.get("conv-domain-3")

    assert persisted is not None
    assert persisted.flight_search.results == state.flight_search.results
    assert persisted.pending_approval is not None
    assert persisted.booking.booking_id is None
    assert follow_up.flight_search.selected_option_id == "LH001"
    assert follow_up.pending_approval is not None


def test_agent_state_round_trips_flight_search_and_booking() -> None:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.flight_search.origin = "TIA"
    state.flight_search.destination = "FRA"
    state.flight_search.date = "2025-09-15"
    state.flight_search.results = mock_flight_options(
        origin="TIA",
        destination="FRA",
        travel_date="2025-09-15",
    )
    state.flight_search.selected_option_id = "LH001"
    state.flight_search.last_status = FlightStatusInfo(
        flight_number="LH400",
        date="2025-09-15",
        origin="FRA",
        destination="JFK",
        status="On Time",
    )
    state.booking.selected_flight = "LH001"
    state.booking.passenger = "Ana Krasniqi"
    state.booking.booking_id = "BK-TEST001"
    state.booking.status = BookingStatus.PENDING

    restored = AgentState.model_validate_json(state.model_dump_json())

    assert restored.flight_search == state.flight_search
    assert restored.booking == state.booking


def test_chat_endpoint_persists_domain_state_in_store() -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    conversation_id = "conv-chat-domain"

    response = client.post(
        "/chat",
        json={
            "message": "Book flights TIA to FRA on 2025-09-15",
            "conversation_id": conversation_id,
        },
    )

    assert response.status_code == 200
    stored = get_state_store().get(conversation_id)

    assert stored is not None
    assert len(stored.flight_search.results) == 3
    assert stored.flight_search.selected_option_id == "LH001"
    assert stored.pending_approval is not None
    assert stored.booking.booking_id is None
