"""Reflection history audit trail tests — Phase 3.8."""

from app.agent.coordinator import execute_step_stub, select_current_step
from app.agent.loop import run_chat
from app.agent.planning import build_default_flight_plan
from app.agent.reflection import evaluate_and_record, record_reflection
from app.agent.state import AgentState, InMemoryStateStore
from app.config import Settings
from app.models.agent import EvaluationResult, EvaluationStatus, ReflectionRecord


def test_reflection_record_serializes_full_audit_fields() -> None:
    record = ReflectionRecord(
        status=EvaluationStatus.ASK_USER,
        issue="User requested fare comparison but pricing is unavailable.",
        message="I can show scheduled flights, but not reliable fare prices.",
        step_id="search",
        trace_id="trace123",
        iteration=2,
    )

    restored = ReflectionRecord.model_validate_json(record.model_dump_json())

    assert restored == record


def test_record_reflection_captures_step_and_trace_context() -> None:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.iteration_count = 3
    state.plan = build_default_flight_plan("Find flights")
    select_current_step(state)

    record = record_reflection(
        state,
        EvaluationResult(
            status=EvaluationStatus.CONTINUE,
            issue=None,
            message=None,
        ),
    )

    assert record.step_id == "search"
    assert record.trace_id == "trace1"
    assert record.iteration == 3
    assert len(state.reflection_history) == 1


def test_evaluate_and_record_populates_full_reflection_entry() -> None:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.user_message = "Book flights TIA to FRA on 2025-09-15"
    state.plan = build_default_flight_plan("Find flights")
    step = select_current_step(state)
    assert step is not None
    execute_step_stub(state, step)

    evaluate_and_record(state)

    record = state.reflection_history[-1]
    assert record.status == EvaluationStatus.CONTINUE
    assert record.step_id == "search"
    assert record.trace_id == "trace1"
    assert record.iteration == 0


def test_reflection_history_survives_agent_state_roundtrip() -> None:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.user_message = "Book flights TIA to FRA on 2025-09-15"
    state.plan = build_default_flight_plan("Find flights")
    step = select_current_step(state)
    assert step is not None
    execute_step_stub(state, step)
    evaluate_and_record(state)

    restored = AgentState.model_validate_json(state.model_dump_json())

    assert len(restored.reflection_history) == 1
    assert restored.reflection_history[0].step_id == "search"
    assert restored.reflection_history[0].status == EvaluationStatus.CONTINUE


def test_reflection_history_records_all_evaluator_outcomes() -> None:
    store = InMemoryStateStore()
    settings = Settings(max_step_retries=1, max_replan_attempts=0)

    continue_state, _ = run_chat(
        user_message="Book flights TIA to FRA on 2025-09-15",
        trace_id="trace-continue",
        store=store,
    )
    retry_state, _ = run_chat(
        user_message="Book flights TIA to FRA on 2025-09-15",
        trace_id="trace-retry",
        store=InMemoryStateStore(),
        settings=settings,
        stub_failures={"search": 3},
    )
    replan_state, _ = run_chat(
        user_message="Book flights TIA to FRA on 2025-09-15",
        trace_id="trace-replan",
        store=InMemoryStateStore(),
        stub_replan=["search"],
    )
    ask_state, _ = run_chat(
        user_message="Find the cheapest flight TIA to FRA",
        trace_id="trace-ask",
        store=InMemoryStateStore(),
    )
    fail_state, _ = run_chat(
        user_message="Book flights TIA to FRA on 2025-09-15",
        trace_id="trace-fail",
        store=InMemoryStateStore(),
        stub_fail_evaluation=["search"],
    )

    continue_statuses = {record.status for record in continue_state.reflection_history}
    retry_statuses = {record.status for record in retry_state.reflection_history}
    replan_statuses = {record.status for record in replan_state.reflection_history}
    ask_statuses = {record.status for record in ask_state.reflection_history}
    fail_statuses = {record.status for record in fail_state.reflection_history}

    assert EvaluationStatus.CONTINUE in continue_statuses
    assert EvaluationStatus.RETRY in retry_statuses
    assert EvaluationStatus.FAIL in retry_statuses
    assert EvaluationStatus.REPLAN in replan_statuses
    assert EvaluationStatus.ASK_USER in ask_statuses
    assert EvaluationStatus.FAIL in fail_statuses

    for state in (continue_state, retry_state, replan_state, ask_state, fail_state):
        assert all(record.trace_id for record in state.reflection_history)
        assert all(record.step_id for record in state.reflection_history)


def test_reflection_history_grows_across_conversation_turns() -> None:
    store = InMemoryStateStore()
    conversation_id = "conv-reflection"

    first_state, _ = run_chat(
        user_message="Find the cheapest flight TIA to FRA",
        trace_id="trace1",
        conversation_id=conversation_id,
        store=store,
    )
    second_state, _ = run_chat(
        user_message="Yes, show me flights by schedule",
        trace_id="trace2",
        conversation_id=conversation_id,
        store=store,
    )

    assert len(first_state.reflection_history) == 1
    assert first_state.reflection_history[0].status == EvaluationStatus.ASK_USER
    assert len(second_state.reflection_history) >= len(first_state.reflection_history)
    assert second_state.reflection_history[-1].trace_id == "trace2"
    assert any(record.trace_id == "trace1" for record in second_state.reflection_history)
