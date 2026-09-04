"""Phase A travel details tests."""

from app.agent.loop import run_chat
from app.agent.state import AgentState, InMemoryStateStore
from app.agent.travel_details import (
    handle_preferences_clarification,
    handle_travel_details_clarification,
    is_explicit_travel_query,
)
from app.models.agent import Language
from app.models.nlu import TravelSlots


def _state(message: str, *, language: Language = Language.EN) -> AgentState:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.user_message = message
    state.language = language
    return state


def test_explicit_travel_query_skips_phase_a_prompts() -> None:
    slots = TravelSlots(
        origin="TIA",
        destination="FRA",
        travel_date="2025-09-15",
        intent="search_flights",
    )

    assert is_explicit_travel_query("Find flights TIA to FRA on 2025-09-15", slots) is True


def test_book_without_date_asks_trip_details_after_date() -> None:
    store = InMemoryStateStore()

    first_state, first_message = run_chat(
        user_message="book my flight from tirana to france",
        trace_id="trace1",
        store=store,
    )
    assert "travel" in first_message.lower()

    second_state, second_message = run_chat(
        user_message="2025-09-15",
        trace_id="trace2",
        conversation_id=first_state.conversation_id,
        store=store,
    )

    assert "one-way" in second_message.lower() or "round-trip" in second_message.lower()
    assert second_state.pending_approval is None


def test_trip_details_then_preferences_then_search() -> None:
    store = InMemoryStateStore()

    run_chat(
        user_message="book my flight from tirana to france",
        trace_id="trace1",
        store=store,
        conversation_id="conv-phase-a",
    )
    run_chat(
        user_message="2025-09-15",
        trace_id="trace2",
        conversation_id="conv-phase-a",
        store=store,
    )
    third_state, third_message = run_chat(
        user_message="one-way, just me",
        trace_id="trace3",
        conversation_id="conv-phase-a",
        store=store,
    )

    assert "preferences" in third_message.lower()
    assert third_state.flight_search.trip_type == "one_way"
    assert third_state.flight_search.passengers == 1

    fourth_state, fourth_message = run_chat(
        user_message="morning, no preference, economy",
        trace_id="trace4",
        conversation_id="conv-phase-a",
        store=store,
    )

    assert "Found" in fourth_message and "mock flights" in fourth_message
    assert "Booking approval required" in fourth_message
    assert fourth_state.flight_search.time_of_day == "morning"
    assert fourth_state.flight_search.cabin_class == "economy"
    assert fourth_state.pending_approval is not None


def test_find_flights_still_skips_phase_a_prompts() -> None:
    store = InMemoryStateStore()

    state, message = run_chat(
        user_message="Find flights TIA to FRA on 2025-09-15",
        trace_id="trace1",
        store=store,
    )

    assert "Found 3 mock flights" in message
    assert "One-way or round-trip" not in message
    assert state.flight_search.selected_option_id is None


def test_round_trip_search_includes_return_leg() -> None:
    store = InMemoryStateStore()

    state, message = run_chat(
        user_message=(
            "Find flights TIA to FRA on 2025-09-15 round-trip returning 2025-09-18, just me, "
            "morning, economy"
        ),
        trace_id="trace1",
        store=store,
    )

    assert "Found 1 mock flights" in message
    assert "Return (FRA → TIA)" in message
    assert state.flight_search.trip_type == "round_trip"
    assert state.flight_search.return_date == "2025-09-18"
    assert len(state.flight_search.return_results) == 1
    assert state.pending_approval is None


def test_handle_travel_details_prompts_when_round_trip_missing_return_date() -> None:
    state = _state("book this")
    state.flight_search.origin = "TIA"
    state.flight_search.destination = "FRA"
    state.flight_search.date = "2025-09-15"
    state.current_intent = "book_flight"
    state.flight_search.trip_type = "round_trip"

    reply = handle_travel_details_clarification(
        state,
        TravelSlots(intent="book_flight", travel_date="2025-09-15", trip_type="round_trip"),
    )

    assert reply is not None
    assert "round-trip" in reply.lower() or "return" in reply.lower()


def test_albanian_one_shot_book_skips_phase_a_prompts() -> None:
    store = InMemoryStateStore()

    state, message = run_chat(
        user_message="Desha te rezervoj nje fluturim TIA to FRA on 2025-09-15",
        trace_id="trace1",
        store=store,
    )

    assert "One-way or round-trip" not in message
    assert state.pending_approval is not None


def test_preferences_can_be_skipped() -> None:
    state = _state("no preference")
    state.flight_search.origin = "TIA"
    state.flight_search.destination = "FRA"
    state.flight_search.date = "2025-09-15"
    state.flight_search.trip_type = "one_way"
    state.flight_search.trip_details_asked = True
    state.user_context["awaiting"] = "preferences"
    state.current_intent = "book_flight"

    reply = handle_preferences_clarification(state, TravelSlots(intent="book_flight"))

    assert reply is None
    assert state.flight_search.preferences_asked is True
