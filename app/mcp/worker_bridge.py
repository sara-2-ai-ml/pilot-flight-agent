"""Map MCP tool payloads onto AgentState for worker actions."""

from __future__ import annotations

from typing import Any

from app.agent.state import AgentState
from app.agent.workers.base import WorkerResult
from app.models.booking import BookingStatus
from app.models.flight import FlightOption
from app.tools.booking_service import parse_passenger_name


def apply_search_results(
    state: AgentState,
    options: list[FlightOption],
    *,
    origin: str,
    destination: str,
    travel_date: str,
    source: str,
) -> WorkerResult:
    if not options:
        return WorkerResult(
            message=f"No flights found from {origin} to {destination} on the requested date.",
            success=False,
        )

    state.flight_search.origin = origin
    state.flight_search.destination = destination
    state.flight_search.date = travel_date
    state.flight_search.results = options
    state.flight_search.selected_option_id = None

    return WorkerResult(
        message=f"Found {len(options)} {source} flights from {origin} to {destination}.",
        success=True,
    )


def apply_validate_options(state: AgentState) -> WorkerResult:
    from app.tools.flight_service import FlightSearchService

    return FlightSearchService().validate_options(state)


def apply_create_booking(state: AgentState, payload: dict[str, Any]) -> WorkerResult:
    if not payload.get("found"):
        error = payload.get("error", "Booking could not be created.")
        return WorkerResult(message=str(error), success=False)

    booking_id = str(payload["booking_id"])
    passenger = str(payload.get("passenger") or parse_passenger_name(state.user_message))
    flight_id = str(payload.get("flight_id") or state.flight_search.selected_option_id or "")

    state.booking.selected_flight = flight_id
    state.booking.passenger = passenger
    state.booking.booking_id = booking_id
    state.booking.status = BookingStatus(str(payload.get("status", BookingStatus.PENDING.value)))

    verb = "Returning existing" if payload.get("idempotent_replay") else "Created"
    return WorkerResult(
        message=(
            f"{verb} booking {booking_id} for flight {flight_id} "
            f"({passenger}, pending confirmation)."
        ),
        success=True,
    )
