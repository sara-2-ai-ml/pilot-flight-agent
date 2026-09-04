"""Reflection / evaluator tests — Phase 3.2, Phase 11.2."""

from app.agent.coordinator import execute_step_stub, select_current_step
from app.agent.loop import run_chat
from app.agent.planning import build_default_flight_plan, build_search_only_plan
from app.agent.reflection import (
    evaluate_and_record,
    evaluate_latest_tool_result,
    evaluate_pricing_availability,
    evaluate_step_result,
    set_stub_ask_user,
    set_stub_fail_evaluation,
)
from app.agent.replanning import set_stub_replan
from app.agent.state import AgentState, InMemoryStateStore
from app.models.agent import EvaluationStatus, ToolCallRecord
from app.models.planning import PlanStatus, StepStatus
from tests.test_replanning import SearchOnlyMockPlanner


def test_evaluate_step_result_returns_continue_for_success() -> None:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.user_message = "Book flights TIA to FRA on 2025-09-15"
    state.current_intent = "book_flight"
    state.plan = build_default_flight_plan("Book flights")
    step = select_current_step(state)
    assert step is not None
    execute_step_stub(state, step)

    result = evaluate_step_result(
        state,
        step=step,
        success=True,
        output="Stub executed flight.search_flights",
    )

    assert result.status == EvaluationStatus.CONTINUE


def test_evaluate_step_result_returns_ask_user_after_search_only() -> None:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.user_message = "Find flights TIA to FRA on 2025-09-15"
    state.current_intent = "search_flights"
    state.plan = build_search_only_plan("Find flights")
    step = select_current_step(state)
    assert step is not None
    execute_step_stub(state, step)

    result = evaluate_step_result(
        state,
        step=step,
        success=True,
        output="Stub executed flight.search_flights",
    )

    assert result.status == EvaluationStatus.ASK_USER
    assert result.message is not None
    assert "LH001" in result.message


def test_evaluate_step_result_returns_retry_for_failure() -> None:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.plan = build_default_flight_plan("Find flights")
    step = select_current_step(state)
    assert step is not None

    result = evaluate_step_result(
        state,
        step=step,
        success=False,
        output="",
        error="Timeout calling flight API",
    )

    assert result.status == EvaluationStatus.RETRY
    assert result.issue == "Timeout calling flight API"


def test_evaluate_step_result_returns_replan_when_stub_triggered() -> None:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.user_message = "Find flights TIA to FRA on 2025-09-15"
    state.plan = build_default_flight_plan("Find flights")
    step = select_current_step(state)
    assert step is not None
    set_stub_replan(state, ["search"])
    execute_step_stub(state, step)

    result = evaluate_step_result(
        state,
        step=step,
        success=True,
        output="Stub executed flight.search_flights",
    )

    assert result.status == EvaluationStatus.REPLAN
    assert result.issue is not None


def test_evaluate_step_result_returns_ask_user_for_cheapest_flight() -> None:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.user_message = "Find the cheapest flight TIA to FRA"
    state.plan = build_default_flight_plan("Find the cheapest flight TIA to FRA")
    step = select_current_step(state)
    assert step is not None
    execute_step_stub(state, step)

    result = evaluate_step_result(
        state,
        step=step,
        success=True,
        output="Stub executed flight.search_flights",
    )

    assert result.status == EvaluationStatus.ASK_USER
    assert result.message is not None
    assert "schedule" in result.message.lower()


def test_evaluate_step_result_returns_ask_user_when_stub_triggered() -> None:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.user_message = "Find flights TIA to FRA on 2025-09-15"
    state.plan = build_default_flight_plan("Find flights")
    step = select_current_step(state)
    assert step is not None
    set_stub_ask_user(state, ["search"])
    execute_step_stub(state, step)

    result = evaluate_step_result(
        state,
        step=step,
        success=True,
        output="Stub executed flight.search_flights",
    )

    assert result.status == EvaluationStatus.ASK_USER


def test_evaluate_pricing_availability_ignores_non_search_steps() -> None:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.user_message = "Find the cheapest flight TIA to FRA"
    state.plan = build_default_flight_plan("Find flights")
    select_step = state.plan.steps[1]

    assert evaluate_pricing_availability(state, step=select_step) is None


def test_evaluate_step_result_returns_fail_when_stub_triggered() -> None:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.user_message = "Find flights TIA to FRA on 2025-09-15"
    state.plan = build_default_flight_plan("Find flights")
    step = select_current_step(state)
    assert step is not None
    set_stub_fail_evaluation(state, ["search"])
    execute_step_stub(state, step)

    result = evaluate_step_result(
        state,
        step=step,
        success=True,
        output="Stub executed flight.search_flights",
    )

    assert result.status == EvaluationStatus.FAIL
    assert result.message is not None


def test_evaluate_latest_tool_result_uses_last_tool_call() -> None:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.user_message = "Book flights TIA to FRA on 2025-09-15"
    state.current_intent = "book_flight"
    state.plan = build_default_flight_plan("Book flights")
    step = select_current_step(state)
    assert step is not None
    execute_step_stub(state, step)

    result = evaluate_latest_tool_result(state)

    assert result.status == EvaluationStatus.CONTINUE


def test_evaluate_and_record_appends_reflection_history() -> None:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.user_message = "Book flights TIA to FRA on 2025-09-15"
    state.current_intent = "book_flight"
    state.plan = build_default_flight_plan("Book flights")
    step = select_current_step(state)
    assert step is not None
    execute_step_stub(state, step)

    result = evaluate_and_record(state)

    assert result.status == EvaluationStatus.CONTINUE
    assert len(state.reflection_history) == 1
    assert state.reflection_history[0].status == EvaluationStatus.CONTINUE


def test_evaluate_and_record_persists_replan_decision() -> None:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.user_message = "Find flights TIA to FRA on 2025-09-15"
    state.plan = build_default_flight_plan("Find flights")
    step = select_current_step(state)
    assert step is not None
    set_stub_replan(state, ["search"])
    execute_step_stub(state, step)

    result = evaluate_and_record(state)

    assert result.status == EvaluationStatus.REPLAN
    assert state.reflection_history[-1].status == EvaluationStatus.REPLAN
    assert state.reflection_history[-1].step_id == "search"


def test_evaluate_and_record_persists_ask_user_decision() -> None:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.user_message = "Find the cheapest flight TIA to FRA"
    state.plan = build_default_flight_plan("Find the cheapest flight TIA to FRA")
    step = select_current_step(state)
    assert step is not None
    execute_step_stub(state, step)

    result = evaluate_and_record(state)

    assert result.status == EvaluationStatus.ASK_USER
    assert state.reflection_history[-1].status == EvaluationStatus.ASK_USER
    assert state.reflection_history[-1].message is not None


def test_evaluate_latest_tool_result_asks_user_for_missing_route() -> None:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.plan = build_default_flight_plan("Find flights")
    select_current_step(state)
    state.tool_history.append(
        ToolCallRecord(
            tool="flight",
            action="search_flights",
            status="failed",
            message="Where would you like to go?",
            error_code="missing_route",
        ),
    )

    result = evaluate_latest_tool_result(state)

    assert result.status == EvaluationStatus.ASK_USER
    assert "Where would you like to go?" in (result.message or "")


def test_evaluate_latest_tool_result_returns_retry_for_failed_tool() -> None:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.plan = build_default_flight_plan("Find flights")
    select_current_step(state)
    state.tool_history.append(
        ToolCallRecord(tool="flight", action="search_flights", status="failed"),
    )

    result = evaluate_latest_tool_result(state)

    assert result.status == EvaluationStatus.RETRY
    assert result.issue is not None


def test_evaluate_latest_tool_result_fails_when_circuit_open() -> None:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.plan = build_default_flight_plan("Find flights")
    select_current_step(state)
    state.tool_history.append(
        ToolCallRecord(
            tool="flight",
            action="search_flights",
            status="failed",
            error_code="circuit_open",
            message=(
                "Flight search is temporarily unavailable due to repeated failures. "
                "Please try again later."
            ),
        ),
    )

    result = evaluate_latest_tool_result(state)

    assert result.status == EvaluationStatus.FAIL
    assert result.message is not None
    assert "temporarily unavailable" in result.message
    assert "circuit breaker" not in result.message.lower()


def test_continue_advances_through_all_plan_steps_in_one_turn() -> None:
    store = InMemoryStateStore()

    state, message = run_chat(
        user_message="Book flights TIA to FRA on 2025-09-15",
        trace_id="trace1",
        store=store,
    )

    assert state.plan.status == PlanStatus.IN_PROGRESS
    assert state.plan.steps[0].status == StepStatus.COMPLETED
    assert state.plan.steps[1].status == StepStatus.COMPLETED
    assert state.plan.steps[2].status == StepStatus.IN_PROGRESS
    assert len(state.tool_history) == 3
    assert len(state.reflection_history) == 2
    assert all(record.status == EvaluationStatus.CONTINUE for record in state.reflection_history)
    assert "Found 3 mock flights from TIA to FRA" in message
    assert "Selected flight LH001" in message
    assert "Booking approval required" in message


def test_run_chat_reflection_replan_replaces_plan() -> None:
    store = InMemoryStateStore()
    planner = SearchOnlyMockPlanner()

    state, message = run_chat(
        user_message="Book flights TIA to FRA on 2025-09-15",
        trace_id="trace-replan",
        store=store,
        planner=planner,
        stub_replan=["search"],
    )

    assert state.replan_count == 1
    assert len(state.plan.steps) == 2
    assert state.reflection_history[0].status == EvaluationStatus.REPLAN
    assert "Replanned with updated strategy." in message
    assert "Booking approval required" in message


def test_run_chat_reflection_ask_user_pauses_execution() -> None:
    store = InMemoryStateStore()

    state, message = run_chat(
        user_message="Find the cheapest flight TIA to FRA",
        trace_id="trace-ask",
        store=store,
    )

    assert state.pending_question is not None
    assert state.plan.status == PlanStatus.COMPLETED
    assert state.reflection_history[-1].status == EvaluationStatus.ASK_USER
    assert "schedule" in message.lower()
