"""Approval payload tests — Phase 7.5."""

from fastapi.testclient import TestClient

from app.agent.loop import run_chat
from app.agent.planning import build_default_flight_plan
from app.agent.state import AgentState, get_state_store
from app.guardrails.approval import build_create_booking_approval, parse_booking_approval
from app.main import app
from app.models.approval import BookingApprovalPayload
from app.tools.flight_client import mock_flight_options


def test_build_create_booking_approval_includes_route_and_flight_details() -> None:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.user_message = "Book flight for Ana Krasniqi"
    state.flight_search.origin = "TIA"
    state.flight_search.destination = "FRA"
    state.flight_search.date = "2025-09-15"
    state.flight_search.results = mock_flight_options(
        origin="TIA",
        destination="FRA",
        travel_date="2025-09-15",
    )
    state.flight_search.selected_option_id = "LH001"
    step = build_default_flight_plan("Book").steps[2]

    payload = build_create_booking_approval(state, step)
    approval = parse_booking_approval(payload)

    assert isinstance(approval, BookingApprovalPayload)
    assert approval.passenger == "Ana Krasniqi"
    assert approval.route.origin == "TIA"
    assert approval.route.destination == "FRA"
    assert approval.route.date == "2025-09-15"
    assert approval.route.origin_city == "Tirana"
    assert approval.route.destination_city == "Frankfurt"
    assert approval.flight.id == "LH001"
    assert approval.flight.departure_time == "2025-09-15T06:30"
    assert approval.flight.arrival_time == "2025-09-15T08:45"
    assert approval.flight_id == "LH001"


def test_chat_response_includes_structured_pending_approval() -> None:
    client = TestClient(app)
    conversation_id = "conv-approval-payload"

    response = client.post(
        "/chat",
        json={
            "message": "Book flights TIA to FRA on 2025-09-15 for Ana Krasniqi",
            "conversation_id": conversation_id,
        },
    )

    assert response.status_code == 200
    body = response.json()
    pending = body["pending_approval"]
    assert pending is not None
    assert pending["passenger"] == "Ana Krasniqi"
    assert pending["route"]["origin"] == "TIA"
    assert pending["route"]["destination"] == "FRA"
    assert pending["route"]["date"] == "2025-09-15"
    assert pending["flight"]["id"] == "LH001"
    assert pending["flight"]["departure_time"] == "2025-09-15T06:30"


def test_get_pending_approval_endpoint_returns_full_payload() -> None:
    client = TestClient(app)
    conversation_id = "conv-approval-get"

    run_chat(
        user_message="Book flights TIA to FRA on 2025-09-15",
        trace_id="trace1",
        conversation_id=conversation_id,
        store=get_state_store(),
    )

    response = client.get("/approvals/pending", params={"conversation_id": conversation_id})

    assert response.status_code == 200
    body = response.json()
    assert body["conversation_id"] == conversation_id
    pending = body["pending_approval"]
    assert pending["flight"]["id"] == "LH001"
    assert pending["route"]["origin_city"] == "Tirana"
    assert pending["route"]["destination_city"] == "Frankfurt"
    assert pending["passenger"] == "Guest Passenger"
