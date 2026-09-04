"""Human approval queue for WRITE worker actions."""

from __future__ import annotations

from app.agent.state import AgentState
from app.models.approval import ApprovalFlight, ApprovalRoute, BookingApprovalPayload
from app.models.flight import FlightOption
from app.models.planning import PlanStep
from app.mcp.servers.airports import get_airport_info
from app.tools.booking_service import parse_passenger_name

APPROVAL_STATUS = "pending_approval"
APPROVAL_CANCELLED_STATUS = "cancelled"


class ApprovalValidationError(ValueError):
    """Raised when a WRITE action cannot be queued for approval."""


def _selected_flight_option(state: AgentState, flight_id: str) -> FlightOption | None:
    for option in state.flight_search.results:
        if option.id == flight_id:
            return option
    return None


def _build_route(state: AgentState, flight_id: str) -> ApprovalRoute:
    selected = _selected_flight_option(state, flight_id)
    origin = (state.flight_search.origin or (selected.origin if selected else "") or "UNK").upper()
    destination = (
        state.flight_search.destination or (selected.destination if selected else "") or "UNK"
    ).upper()
    travel_date = state.flight_search.date or ""
    if not travel_date and selected is not None and "T" in selected.departure_time:
        travel_date = selected.departure_time.split("T", maxsplit=1)[0]
    if not travel_date:
        travel_date = "unknown"

    origin_info = get_airport_info(origin) if origin != "UNK" else {}
    destination_info = get_airport_info(destination) if destination != "UNK" else {}

    return ApprovalRoute(
        origin=origin,
        destination=destination,
        date=travel_date,
        origin_city=origin_info.get("city"),
        destination_city=destination_info.get("city"),
    )


def _build_flight(state: AgentState, flight_id: str) -> ApprovalFlight:
    selected = _selected_flight_option(state, flight_id)
    if selected is not None:
        return ApprovalFlight(
            id=selected.id,
            carrier=selected.carrier,
            origin=selected.origin,
            destination=selected.destination,
            departure_time=selected.departure_time,
            arrival_time=selected.arrival_time,
        )

    origin = (state.flight_search.origin or flight_id[:3]).upper()
    destination = (state.flight_search.destination or flight_id[:3]).upper()
    travel_date = state.flight_search.date or ""
    return ApprovalFlight(
        id=flight_id,
        carrier=flight_id[:2] if len(flight_id) >= 2 else "LH",
        origin=origin,
        destination=destination,
        departure_time=travel_date,
        arrival_time=travel_date,
    )


def build_create_booking_approval(state: AgentState, step: PlanStep) -> dict[str, object]:
    """Build the full approval payload for a pending booking request."""
    flight_id = state.flight_search.selected_option_id
    if flight_id is None:
        raise ApprovalValidationError(
            "No validated flight selected. Validate options before booking.",
        )

    payload = BookingApprovalPayload(
        action="create_booking",
        step_id=step.id,
        worker=step.worker.value,
        conversation_id=state.conversation_id,
        passenger=parse_passenger_name(state.user_message),
        route=_build_route(state, flight_id),
        flight=_build_flight(state, flight_id),
    )
    return payload.model_dump()


def parse_booking_approval(payload: dict[str, object]) -> BookingApprovalPayload:
    """Parse a stored pending approval payload."""
    return BookingApprovalPayload.model_validate(payload)


def format_approval_message(payload: dict[str, object]) -> str:
    """Return a user-facing message for one queued approval."""
    action = payload.get("action")
    if action == "create_booking":
        approval = parse_booking_approval(payload)
        route = approval.route
        flight = approval.flight
        route_label = f"{route.origin} → {route.destination} on {route.date}"
        if route.origin_city and route.destination_city:
            route_label = (
                f"{route.origin_city} ({route.origin}) → "
                f"{route.destination_city} ({route.destination}) on {route.date}"
            )
        return (
            f"Booking approval required: {route_label} | "
            f"{flight.id} dep {flight.departure_time} for {approval.passenger}. "
            "Confirm to create the reservation."
        )
    return "Approval required before this action can proceed."


def queue_step_for_approval(state: AgentState, step: PlanStep) -> str:
    """Queue one WRITE plan step for human approval without side effects."""
    if step.action != "create_booking":
        raise ApprovalValidationError(f"Unsupported approval action '{step.action}'.")

    payload = build_create_booking_approval(state, step)
    state.pending_approval = payload
    return format_approval_message(payload)
