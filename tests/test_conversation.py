"""Conversation handler tests."""

from app.agent.conversation import (
    handle_turn_during_pending_approval,
    is_date_change_intent,
    should_ask_for_travel_date,
)
from app.agent.loop import run_chat
from app.agent.state import AgentState, InMemoryStateStore
from app.guardrails.approval import queue_step_for_approval
from app.models.nlu import TravelSlots
from app.models.planning import PlanStep, Worker


def _state(message: str) -> AgentState:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.user_message = message
    state.flight_search.origin = "TIA"
    state.flight_search.destination = "CDG"
    state.flight_search.date = "2026-09-04"
    state.flight_search.selected_option_id = "LH001"
    return state


def _queue_approval(state: AgentState) -> None:
    step = PlanStep(id="booking", worker=Worker.BOOKING, action="create_booking")
    queue_step_for_approval(state, step)


def test_confirm_intent_does_not_match_substrings() -> None:
    from app.agent.conversation import is_confirm_intent

    assert is_confirm_intent("Any updates?") is False
    assert is_confirm_intent("ok book it") is True


def test_should_ask_for_travel_date_on_book_without_date() -> None:
    slots = TravelSlots(
        intent="book_flight",
        origin="TIA",
        destination="CDG",
        travel_date=None,
    )

    assert should_ask_for_travel_date(slots, "book my flight tirana to france") is True


def test_date_change_intent_detected() -> None:
    assert is_date_change_intent("i have to choose date") is True


def test_pending_approval_date_change_resets_hold() -> None:
    state = _state("i have to choose date")
    _queue_approval(state)

    reply = handle_turn_during_pending_approval(
        state,
        TravelSlots(intent="other"),
    )

    assert state.pending_approval is None
    assert reply is not None
    assert "travel" in reply.lower()


def test_pending_approval_confirm_guidance() -> None:
    state = _state("yes confirm")
    _queue_approval(state)

    reply = handle_turn_during_pending_approval(
        state,
        TravelSlots(intent="other"),
    )

    assert state.pending_approval is not None
    assert "Pay & book" in (reply or "")


def test_pending_approval_complaint_resets() -> None:
    state = _state("you made things wrong")
    _queue_approval(state)

    reply = handle_turn_during_pending_approval(
        state,
        TravelSlots(intent="other"),
    )

    assert state.pending_approval is None
    assert "sorry" in (reply or "").lower()


def test_run_chat_asks_for_date_before_booking() -> None:
    store = InMemoryStateStore()

    _state, message = run_chat(
        user_message="book my flight from tirana to france",
        trace_id="trace1",
        store=store,
    )

    assert "travel" in message.lower()
    assert "TIA" in message or "tirana" in message.lower()
    assert _state.pending_approval is None


def test_run_chat_during_pending_approval_keeps_context() -> None:
    store = InMemoryStateStore()

    first_state, _ = run_chat(
        user_message="Book flights TIA to FRA on 2025-09-15",
        trace_id="trace1",
        store=store,
    )
    assert first_state.pending_approval is not None

    second_state, message = run_chat(
        user_message="i have to choose date",
        trace_id="trace2",
        conversation_id=first_state.conversation_id,
        store=store,
    )

    assert "travel" in message.lower()
    assert second_state.pending_approval is None
    assert "I'm ready to help" not in message
