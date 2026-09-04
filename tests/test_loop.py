"""Agent loop tests — Phase 1.4."""

from app.agent.loop import run_chat
from app.agent.state import AgentState, InMemoryStateStore
from app.config import Settings
from app.models.agent import EvaluationStatus, Language
from app.models.planning import PlanStatus, StepStatus, Plan, PlanStep, Worker
from tests.test_replanning import SearchOnlyMockPlanner


class SearchOnlyPlanner:
    """Always returns a single search step — simulates LLM search-only output."""

    def create_plan(self, state: AgentState) -> Plan:
        return Plan(
            goal=state.user_message,
            steps=[PlanStep(id="search", worker=Worker.FLIGHT, action="search_flights")],
        )

def test_run_chat_creates_and_updates_state() -> None:
    store = InMemoryStateStore()

    state, message = run_chat(
        user_message="Find flights TIA to FRA",
        trace_id="trace1",
        store=store,
    )

    assert "Found 3 mock flights from TIA to FRA" in message
    assert "LH001" in message
    assert "Selected flight LH001" not in message
    assert state.iteration_count == 1
    assert state.user_message == "Find flights TIA to FRA"
    assert state.language == Language.EN
    assert state.plan.status == PlanStatus.COMPLETED
    assert len(state.flight_search.results) == 3
    assert state.flight_search.selected_option_id is None
    assert state.pending_approval is None
    assert state.pending_question is not None
    assert state.booking.booking_id is None

    persisted = store.get(state.conversation_id)
    assert persisted is not None
    assert persisted.iteration_count == 1


def test_run_chat_expands_search_only_plan_to_hitl() -> None:
    store = InMemoryStateStore()

    state, message = run_chat(
        user_message="Book flights TIA to FRA on 2025-09-15",
        trace_id="trace1",
        store=store,
        planner=SearchOnlyPlanner(),
    )

    assert "Found 3 mock flights from TIA to FRA" in message
    assert "Booking approval required" in message
    assert state.pending_approval is not None
    assert "Pilot received:" not in message


def test_run_chat_reuses_conversation_state() -> None:
    store = InMemoryStateStore()

    first_state, _ = run_chat(
        user_message="Find flights TIA to FRA",
        trace_id="trace1",
        conversation_id="conv1",
        store=store,
    )
    second_state, second_message = run_chat(
        user_message="Again",
        trace_id="trace2",
        conversation_id="conv1",
        store=store,
    )

    assert first_state.conversation_id == second_state.conversation_id == "conv1"
    assert second_state.iteration_count == 2
    assert second_state.trace_id == "trace2"
    assert second_state.user_message == "Again"
    assert first_state.plan.status == PlanStatus.COMPLETED
    assert "Stub executed" not in second_message


def test_run_chat_detects_albanian_hint() -> None:
    store = InMemoryStateStore()

    state, _ = run_chat(
        user_message="Desha te rezervoj nje fluturim",
        trace_id="trace1",
        store=store,
    )

    assert state.language == Language.SQ


def test_run_chat_stops_when_budget_exceeded() -> None:
    store = InMemoryStateStore()
    settings = Settings(max_iterations=1)

    _, first_message = run_chat(
        user_message="Find flights TIA to FRA",
        trace_id="t1",
        conversation_id="c1",
        settings=settings,
        store=store,
    )
    state, second_message = run_chat(
        user_message="Second",
        trace_id="t2",
        conversation_id="c1",
        settings=settings,
        store=store,
    )

    assert "Found 3 mock" in first_message
    assert "budget exceeded" in second_message.lower()
    assert state.iteration_count == 2


def test_run_chat_stores_plan_in_state() -> None:
    store = InMemoryStateStore()

    state, _ = run_chat(
        user_message="Book flights TIA to FRA on 2025-09-15",
        trace_id="trace1",
        store=store,
    )

    assert len(state.plan.steps) == 3
    assert state.plan.status == PlanStatus.IN_PROGRESS
    assert "Book flights" in state.plan.goal
    assert "TIA" in state.plan.goal
    assert "FRA" in state.plan.goal
    assert state.plan.steps[0].status == StepStatus.COMPLETED
    assert state.plan.steps[1].status == StepStatus.COMPLETED
    assert state.plan.steps[2].status == StepStatus.IN_PROGRESS
    assert len(state.tool_history) == 3
    assert len(state.reflection_history) == 2
    assert all(record.status == EvaluationStatus.CONTINUE for record in state.reflection_history)


def test_run_chat_completes_plan_in_single_request() -> None:
    store = InMemoryStateStore()

    state, message = run_chat(
        user_message="Book flights TIA to FRA on 2025-09-15",
        trace_id="trace1",
        store=store,
    )

    assert state.plan.status == PlanStatus.IN_PROGRESS
    assert "Booking approval required" in message


def test_run_chat_retries_failed_step_then_continues() -> None:
    store = InMemoryStateStore()
    settings = Settings(max_step_retries=3)

    state, message = run_chat(
        user_message="Find flights TIA to FRA",
        trace_id="trace1",
        store=store,
        settings=settings,
        stub_failures={"search": 2},
    )

    assert state.plan.status == PlanStatus.COMPLETED
    assert state.step_retry_counts.get("search") == 2
    assert sum(1 for record in state.reflection_history if record.status == EvaluationStatus.RETRY) == 2
    assert "Found 3 mock flights from TIA to FRA" in message
    assert len(state.reflection_history) >= 3


def test_run_chat_fails_after_max_retries() -> None:
    store = InMemoryStateStore()
    settings = Settings(max_step_retries=2)

    state, _message = run_chat(
        user_message="Find flights TIA to FRA",
        trace_id="trace1",
        store=store,
        settings=settings,
        stub_failures={"search": 5},
    )

    assert state.plan.status == PlanStatus.FAILED
    assert state.reflection_history[-1].status == EvaluationStatus.FAIL
    assert state.step_retry_counts["search"] == 2
    assert "Stub failed" not in _message
    assert "couldn't complete this step" in _message.lower()


def test_run_chat_returns_graceful_fail_from_evaluator() -> None:
    store = InMemoryStateStore()

    state, message = run_chat(
        user_message="Find flights TIA to FRA",
        trace_id="trace1",
        store=store,
        stub_fail_evaluation=["search"],
    )

    assert state.plan.status == PlanStatus.FAILED
    assert state.reflection_history[-1].status == EvaluationStatus.FAIL
    assert "Stub failed" not in message
    assert "couldn't complete your request" in message.lower()


def test_run_chat_replans_and_completes_new_plan() -> None:
    store = InMemoryStateStore()
    planner = SearchOnlyMockPlanner()

    state, message = run_chat(
        user_message="Book flights TIA to FRA on 2025-09-15",
        trace_id="trace1",
        store=store,
        planner=planner,
        stub_replan=["search"],
    )

    assert state.replan_count == 1
    assert len(state.plan.steps) == 2
    assert state.plan.status == PlanStatus.IN_PROGRESS
    assert EvaluationStatus.REPLAN in {record.status for record in state.reflection_history}
    assert "Replanned with updated strategy." in message
    assert "Booking approval required" in message


def test_run_chat_fails_after_max_replan_attempts() -> None:
    store = InMemoryStateStore()
    settings = Settings(max_replan_attempts=1)
    planner = SearchOnlyMockPlanner()

    state, _message = run_chat(
        user_message="Find flights TIA to FRA",
        trace_id="trace1",
        store=store,
        settings=settings,
        planner=planner,
        stub_replan=["search", "search"],
    )

    assert state.replan_count == 1
    assert state.reflection_history[-1].status == EvaluationStatus.FAIL
    assert any(record.status == EvaluationStatus.REPLAN for record in state.reflection_history)


def test_run_chat_asks_user_for_cheapest_flight_without_prices() -> None:
    store = InMemoryStateStore()

    state, message = run_chat(
        user_message="Find the cheapest flight TIA to FRA",
        trace_id="trace1",
        store=store,
    )

    assert state.pending_question is not None
    assert state.plan.status == PlanStatus.COMPLETED
    assert state.plan.steps[0].status == StepStatus.COMPLETED
    assert state.reflection_history[-1].status == EvaluationStatus.ASK_USER
    assert "schedule" in message.lower()
    assert "Created booking BK-" not in message


def test_run_chat_resumes_plan_after_user_replies() -> None:
    store = InMemoryStateStore()

    first_state, first_message = run_chat(
        user_message="Find the cheapest flight TIA to FRA",
        trace_id="trace1",
        conversation_id="conv1",
        store=store,
    )
    second_state, second_message = run_chat(
        user_message="Yes, show me flights by schedule",
        trace_id="trace2",
        conversation_id="conv1",
        store=store,
    )

    assert first_state.pending_question is not None
    assert "schedule" in first_message.lower()
    assert second_state.plan.status == PlanStatus.COMPLETED
    assert "LH001" in second_message
    assert "Booking approval required" not in second_message


def test_run_chat_asks_for_route_on_greeting() -> None:
    store = InMemoryStateStore()

    state, message = run_chat(
        user_message="hi",
        trace_id="trace1",
        store=store,
    )

    assert "flying from" in message.lower() or "Where" in message
    assert "TIA" not in message
    assert state.pending_question is not None
    assert state.plan.steps == []
    assert "couldn't complete" not in message.lower()


def test_run_chat_asks_for_route_on_vague_booking_request() -> None:
    store = InMemoryStateStore()

    state, message = run_chat(
        user_message="i want a ticket",
        trace_id="trace1",
        store=store,
    )

    assert "flying from" in message.lower() or "Where" in message
    assert "TIA" not in message
    assert state.pending_question is not None
    assert state.plan.steps == []


def test_run_chat_recovers_after_clarification_with_route() -> None:
    store = InMemoryStateStore()
    conversation_id = "conv-clarify"

    _, first_message = run_chat(
        user_message="hi",
        trace_id="trace1",
        conversation_id=conversation_id,
        store=store,
    )
    state, second_message = run_chat(
        user_message="TIA to FRA on 2025-09-15",
        trace_id="trace2",
        conversation_id=conversation_id,
        store=store,
    )

    assert "flying from" in first_message.lower() or "Where" in first_message
    assert "Found 3 mock flights from TIA to FRA" in second_message
    assert state.flight_search.origin == "TIA"
    assert state.flight_search.destination == "FRA"
    assert state.plan.status == PlanStatus.COMPLETED
