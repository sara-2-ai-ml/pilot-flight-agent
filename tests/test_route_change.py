"""Route change and destination clarification tests."""

from app.agent.loop import run_chat
from app.agent.state import InMemoryStateStore


def test_destination_change_after_search_does_not_idle() -> None:
    store = InMemoryStateStore()

    first_state, _ = run_chat(
        user_message="Find flights TIA to FRA on 2025-09-15",
        trace_id="trace1",
        conversation_id="conv-route-change",
        store=store,
    )
    assert first_state.flight_search.destination == "FRA"

    second_state, second_message = run_chat(
        user_message="i want to go to belgium",
        trace_id="trace2",
        conversation_id="conv-route-change",
        store=store,
    )

    assert "Where would you like to fly from" in second_message or "flying from" in second_message.lower()
    assert second_state.flight_search.destination == "BRU"
    assert second_state.flight_search.origin is None
    assert second_state.flight_search.results == []


def test_find_tickets_after_destination_change_does_not_reuse_old_route() -> None:
    store = InMemoryStateStore()
    conversation_id = "conv-find-tickets"

    run_chat(
        user_message="Find flights TIA to FRA on 2025-09-15",
        trace_id="trace1",
        conversation_id=conversation_id,
        store=store,
    )
    run_chat(
        user_message="i want to go to belgium",
        trace_id="trace2",
        conversation_id=conversation_id,
        store=store,
    )
    third_state, third_message = run_chat(
        user_message="find me tickets",
        trace_id="trace3",
        conversation_id=conversation_id,
        store=store,
    )

    assert "FRA" not in third_message or "e.g." in third_message
    assert (
        "Where would you like to fly from" in third_message
        or "flying from" in third_message.lower()
        or "Where would you like to go" in third_message
    )
    assert third_state.flight_search.destination == "BRU"
    assert third_state.flight_search.origin is None


def test_complaint_resets_stale_results() -> None:
    store = InMemoryStateStore()
    conversation_id = "conv-complaint"

    run_chat(
        user_message="Find flights TIA to FRA on 2025-09-15",
        trace_id="trace1",
        conversation_id=conversation_id,
        store=store,
    )
    state, message = run_chat(
        user_message="no these are wrong",
        trace_id="trace2",
        conversation_id=conversation_id,
        store=store,
    )

    assert "Sorry about the confusion" in message or "confusion" in message.lower()
    assert state.flight_search.results == []
    assert state.flight_search.origin is None
    assert state.flight_search.destination is None


def test_tirane_belgium_this_month_asks_for_day_before_search() -> None:
    store = InMemoryStateStore()

    state, message = run_chat(
        user_message="so tirane to belgium this month , find cheapest price",
        trace_id="trace1",
        store=store,
    )

    assert "day" in message.lower() and "month" in message.lower()
    assert state.flight_search.origin == "TIA"
    assert state.flight_search.destination == "BRU"
    assert state.flight_search.results == []
