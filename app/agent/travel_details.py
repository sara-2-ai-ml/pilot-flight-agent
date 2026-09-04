"""Phase A travel details — trip type, passengers, and preferences before search."""

from __future__ import annotations

import re

from app.agent.state import AgentState
from app.models.agent import Language
from app.models.nlu import TravelSlots
from app.tools.flight_service import parse_route, parse_travel_date

_AWAITING_TRIP_DETAILS = "trip_details"
_AWAITING_PREFERENCES = "preferences"

_ROUND_TRIP_HINTS = (
    "round trip",
    "round-trip",
    "return trip",
    "vajtje ardhje",
    "vajtje-ardhje",
    "vajtje dhe ardhje",
)
_ONE_WAY_HINTS = (
    "one way",
    "one-way",
    "one way only",
    "vetem nisje",
    "vetëm nisje",
    "single leg",
)
_SKIP_PREFERENCE_HINTS = (
    "any",
    "no preference",
    "no preferences",
    "doesn't matter",
    "doesnt matter",
    "open to all",
    "all airlines",
    "pa preferenc",
    "cilado",
    "cdo",
)
_PASSENGER_PATTERN = re.compile(
    r"\b(\d+)\s+(?:passengers?|people|persons?|adults?|persona)\b",
    re.IGNORECASE,
)
_JUST_ME_HINTS = ("just me", "only me", "vetem un", "vetëm unë", "solo")
_TIME_OF_DAY_MAP = {
    "morning": "morning",
    "mëngjes": "morning",
    "mengjes": "morning",
    "afternoon": "afternoon",
    "mbasdite": "afternoon",
    "evening": "evening",
    "mbrëmje": "evening",
    "mremje": "evening",
    "night": "evening",
}
_CABIN_CLASS_MAP = {
    "economy": "economy",
    "premium economy": "premium_economy",
    "premium_economy": "premium_economy",
    "business": "business",
    "first class": "first",
    "first": "first",
}


def parse_trip_type(message: str) -> str | None:
    lowered = message.lower()
    if any(hint in lowered for hint in _ROUND_TRIP_HINTS):
        return "round_trip"
    if any(hint in lowered for hint in _ONE_WAY_HINTS):
        return "one_way"
    return None


def parse_return_date(message: str) -> str | None:
    return_match = re.search(
        r"\breturn(?:ing)?(?:\s+on|\s+date)?\s+(\d{4}-\d{2}-\d{2})\b",
        message,
        re.IGNORECASE,
    )
    if return_match:
        return return_match.group(1)

    dates = re.findall(r"\b\d{4}-\d{2}-\d{2}\b", message)
    if len(dates) >= 2:
        return dates[1]
    return None


def parse_passengers(message: str) -> int | None:
    lowered = message.lower()
    if any(hint in lowered for hint in _JUST_ME_HINTS):
        return 1

    match = _PASSENGER_PATTERN.search(message)
    if match:
        count = int(match.group(1))
        return max(1, min(count, 9))
    return None


def parse_time_of_day(message: str) -> str | None:
    lowered = message.lower()
    for hint, value in _TIME_OF_DAY_MAP.items():
        if hint in lowered:
            return value
    return None


def parse_airline_preference(message: str) -> str | None:
    match = re.search(r"\b([A-Z]{2})\b(?:\s+only|\s+preferred|\s+airline)?", message)
    if match and match.group(1) not in {"TO", "ON", "IN", "AT", "OR", "NO"}:
        return match.group(1).upper()
    return None


def parse_cabin_class(message: str) -> str | None:
    lowered = message.lower()
    for hint, value in sorted(_CABIN_CLASS_MAP.items(), key=lambda item: len(item[0]), reverse=True):
        if hint in lowered:
            return value
    return None


def is_explicit_travel_query(message: str, slots: TravelSlots) -> bool:
    """One-shot find/book messages with route and date skip Phase A prompts."""
    origin = slots.origin
    destination = slots.destination
    travel_date = slots.travel_date
    if not origin or not destination:
        parsed_origin, parsed_destination = parse_route(message)
        origin = origin or parsed_origin
        destination = destination or parsed_destination
    if not travel_date:
        travel_date = parse_travel_date(message)

    if not (origin and destination and travel_date):
        return False

    if slots.intent == "book_flight":
        return True

    lowered = message.lower()
    return re.search(r"\b(find|search)\b", lowered) is not None


def _effective_route(state: AgentState, slots: TravelSlots) -> tuple[str | None, str | None]:
    origin = slots.origin or state.flight_search.origin
    destination = slots.destination or state.flight_search.destination
    if origin and destination:
        return origin, destination
    return parse_route(state.user_message)


def _effective_travel_date(state: AgentState, slots: TravelSlots) -> str | None:
    return slots.travel_date or state.flight_search.date or parse_travel_date(state.user_message)


def _wants_booking(state: AgentState, slots: TravelSlots) -> bool:
    from app.agent.planning import user_wants_booking

    if user_wants_booking(state):
        return True
    if slots.intent == "book_flight" and (
        slots.has_route or slots.travel_date or slots.trip_type or slots.return_date
    ):
        return True
    return False


def _preferences_skipped(message: str) -> bool:
    lowered = message.lower()
    return any(hint in lowered for hint in _SKIP_PREFERENCE_HINTS)


def apply_travel_detail_slots(state: AgentState, slots: TravelSlots, *, message: str) -> None:
    """Merge Phase A slots and heuristics onto session flight search state."""
    if slots.trip_type:
        state.flight_search.trip_type = slots.trip_type
    else:
        parsed_trip = parse_trip_type(message)
        if parsed_trip:
            state.flight_search.trip_type = parsed_trip

    if slots.return_date:
        state.flight_search.return_date = slots.return_date
    else:
        parsed_return = parse_return_date(message)
        if parsed_return:
            state.flight_search.return_date = parsed_return

    if slots.passengers is not None:
        state.flight_search.passengers = max(1, min(slots.passengers, 9))
    else:
        parsed_passengers = parse_passengers(message)
        if parsed_passengers is not None:
            state.flight_search.passengers = parsed_passengers

    if slots.time_of_day:
        state.flight_search.time_of_day = slots.time_of_day
    else:
        parsed_time = parse_time_of_day(message)
        if parsed_time:
            state.flight_search.time_of_day = parsed_time

    if slots.airline_preference:
        state.flight_search.airline_preference = slots.airline_preference.upper()
    else:
        parsed_airline = parse_airline_preference(message)
        if parsed_airline:
            state.flight_search.airline_preference = parsed_airline

    if slots.cabin_class:
        state.flight_search.cabin_class = slots.cabin_class
    else:
        parsed_cabin = parse_cabin_class(message)
        if parsed_cabin:
            state.flight_search.cabin_class = parsed_cabin


def ensure_travel_defaults(state: AgentState, slots: TravelSlots, *, message: str) -> None:
    """Default Phase A fields for explicit one-shot travel queries."""
    if not is_explicit_travel_query(message, slots):
        return
    if state.flight_search.trip_type is None:
        state.flight_search.trip_type = "one_way"
    state.flight_search.trip_details_asked = True
    state.flight_search.preferences_asked = True


def _trip_details_complete(state: AgentState) -> bool:
    if state.flight_search.trip_type is None:
        return False
    if state.flight_search.trip_type == "round_trip" and not state.flight_search.return_date:
        return False
    return True


def trip_details_prompt(state: AgentState) -> str:
    from app.agent.conversational_prompts import generate_agent_message

    return generate_agent_message(
        state,
        "travel_details",
        origin=state.flight_search.origin,
        destination=state.flight_search.destination,
    )


def preferences_prompt(state: AgentState) -> str:
    from app.agent.conversational_prompts import generate_agent_message

    return generate_agent_message(state, "preferences")


def _consume_awaiting_trip_details(state: AgentState, slots: TravelSlots) -> bool:
    if state.user_context.get("awaiting") != _AWAITING_TRIP_DETAILS:
        return False

    apply_travel_detail_slots(state, slots, message=state.user_message)
    if state.flight_search.trip_type is None:
        state.flight_search.trip_type = "one_way"
    state.flight_search.trip_details_asked = True
    state.user_context.pop("awaiting", None)
    return True


def _consume_awaiting_preferences(state: AgentState, slots: TravelSlots) -> bool:
    if state.user_context.get("awaiting") != _AWAITING_PREFERENCES:
        return False

    if not _preferences_skipped(state.user_message):
        apply_travel_detail_slots(state, slots, message=state.user_message)
    state.flight_search.preferences_asked = True
    state.user_context.pop("awaiting", None)
    return True


def handle_travel_details_clarification(
    state: AgentState,
    slots: TravelSlots,
) -> str | None:
    """Ask for or consume trip-type / passenger details before booking search."""
    if _consume_awaiting_trip_details(state, slots):
        return None

    if not _wants_booking(state, slots):
        return None

    origin, destination = _effective_route(state, slots)
    travel_date = _effective_travel_date(state, slots)
    if not (origin and destination and travel_date):
        return None

    if is_explicit_travel_query(state.user_message, slots):
        ensure_travel_defaults(state, slots, message=state.user_message)
        return None

    if state.flight_search.trip_details_asked and _trip_details_complete(state):
        return None

    apply_travel_detail_slots(state, slots, message=state.user_message)
    if _trip_details_complete(state):
        state.flight_search.trip_details_asked = True
        return None

    state.user_context["awaiting"] = _AWAITING_TRIP_DETAILS
    return trip_details_prompt(state)


def handle_preferences_clarification(
    state: AgentState,
    slots: TravelSlots,
) -> str | None:
    """Ask for or consume travel preferences before booking search."""
    if _consume_awaiting_preferences(state, slots):
        return None

    if not _wants_booking(state, slots):
        return None

    origin, destination = _effective_route(state, slots)
    travel_date = _effective_travel_date(state, slots)
    if not (origin and destination and travel_date):
        return None

    if is_explicit_travel_query(state.user_message, slots):
        ensure_travel_defaults(state, slots, message=state.user_message)
        return None

    if not state.flight_search.trip_details_asked or not _trip_details_complete(state):
        return None

    if state.flight_search.preferences_asked:
        return None

    apply_travel_detail_slots(state, slots, message=state.user_message)
    if (
        state.flight_search.time_of_day
        or state.flight_search.airline_preference
        or state.flight_search.cabin_class
        or _preferences_skipped(state.user_message)
    ):
        state.flight_search.preferences_asked = True
        return None

    state.user_context["awaiting"] = _AWAITING_PREFERENCES
    return preferences_prompt(state)
