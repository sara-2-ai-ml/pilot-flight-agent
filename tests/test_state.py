"""AgentState tests — Phase 1.1–1.2."""

from app.agent.state import (
    AgentState,
    InMemoryStateStore,
    create_state_for_turn,
    detect_language,
    get_state_store,
    update_from_user_message,
)
from app.models.agent import Language
from app.models.booking import BookingStatus
from app.models.planning import PlanStatus


def test_agent_state_serializes_to_json() -> None:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.user_message = "Hello"
    state.language = Language.EN
    state.iteration_count = 1

    restored = AgentState.model_validate_json(state.model_dump_json())

    assert restored.conversation_id == "conv1"
    assert restored.trace_id == "trace1"
    assert restored.user_message == "Hello"
    assert restored.language == Language.EN
    assert restored.plan.status == PlanStatus.PENDING
    assert restored.booking.status == BookingStatus.NONE


def test_agent_state_has_expected_defaults() -> None:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")

    assert state.user_message == ""
    assert state.language == Language.UNKNOWN
    assert state.current_intent is None
    assert state.plan.steps == []
    assert state.flight_search.results == []
    assert state.tool_history == []
    assert state.reflection_history == []
    assert state.pending_approval is None
    assert state.iteration_count == 0
    assert state.llm_call_count == 0
    assert state.token_usage == 0


def test_create_state_for_turn_stores_request_fields() -> None:
    state = create_state_for_turn(
        conversation_id="conv1",
        trace_id="trace1",
        user_message="Find flights TIA to FRA",
    )

    assert state.conversation_id == "conv1"
    assert state.trace_id == "trace1"
    assert state.user_message == "Find flights TIA to FRA"
    assert state.language == Language.EN


def test_update_from_user_message_refreshes_trace_id() -> None:
    state = AgentState.new(conversation_id="conv1", trace_id="trace_old")
    update_from_user_message(
        state,
        user_message="Desha te rezervoj nje fluturim",
        trace_id="trace_new",
    )

    assert state.trace_id == "trace_new"
    assert state.user_message == "Desha te rezervoj nje fluturim"
    assert state.language == Language.SQ


def test_detect_language() -> None:
    assert detect_language("Book a flight to Frankfurt") == Language.EN
    assert detect_language("Desha te rezervoj nje fluturim") == Language.SQ


def test_in_memory_store_persists_session() -> None:
    store = InMemoryStateStore()
    state = create_state_for_turn(
        conversation_id="conv1",
        trace_id="trace1",
        user_message="Hello",
    )
    state.iteration_count = 2

    store.save(state)
    loaded = store.get("conv1")

    assert loaded is not None
    assert loaded.conversation_id == "conv1"
    assert loaded.user_message == "Hello"
    assert loaded.iteration_count == 2


def test_same_conversation_returns_same_state() -> None:
    store = InMemoryStateStore()

    first = create_state_for_turn(
        conversation_id="conv1",
        trace_id="trace1",
        user_message="First message",
    )
    store.save(first)

    loaded = store.get("conv1")
    assert loaded is not None
    assert loaded.conversation_id == first.conversation_id
    assert loaded.user_message == "First message"


def test_store_get_returns_none_for_unknown_conversation() -> None:
    store = InMemoryStateStore()
    assert store.get("missing") is None


def test_store_get_returns_copy_not_shared_reference() -> None:
    store = InMemoryStateStore()
    state = create_state_for_turn(
        conversation_id="conv1",
        trace_id="trace1",
        user_message="Hello",
    )
    store.save(state)

    loaded = store.get("conv1")
    assert loaded is not None
    loaded.user_message = "Changed"

    reloaded = store.get("conv1")
    assert reloaded is not None
    assert reloaded.user_message == "Hello"


def test_get_state_store_returns_singleton() -> None:
    get_state_store().clear()
    assert get_state_store() is get_state_store()


