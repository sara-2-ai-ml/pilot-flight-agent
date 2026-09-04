"""Tool history audit trail tests — Phase 4.6."""

from app.agent.coordinator import execute_step, select_current_step
from app.agent.loop import run_chat
from app.agent.planning import build_default_flight_plan
from app.agent.state import AgentState, InMemoryStateStore
from app.agent.tool_history import record_tool_call
from app.models.agent import ToolCallRecord
from app.models.planning import StepStatus


def test_tool_call_record_serializes_full_audit_fields() -> None:
    record = ToolCallRecord(
        tool="flight",
        action="search_flights",
        status="completed",
        step_id="search",
        trace_id="trace123",
        message="Found 3 mock flights from TIA to FRA.",
        iteration=1,
    )

    restored = ToolCallRecord.model_validate_json(record.model_dump_json())

    assert restored == record


def test_record_tool_call_captures_step_and_trace_context() -> None:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.iteration_count = 2
    state.plan = build_default_flight_plan("Find flights")
    step = select_current_step(state)
    assert step is not None

    record = record_tool_call(
        state,
        step=step,
        status=StepStatus.COMPLETED.value,
        message="Found 3 mock flights from TIA to FRA.",
    )

    assert record.step_id == "search"
    assert record.trace_id == "trace1"
    assert record.iteration == 2
    assert record.message is not None
    assert len(state.tool_history) == 1


def test_execute_step_records_full_tool_history_entry() -> None:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.user_message = "Book flights TIA to FRA on 2025-09-15"
    state.plan = build_default_flight_plan("Find flights")
    step = select_current_step(state)
    assert step is not None

    execute_step(state, step)

    record = state.tool_history[-1]
    assert record.tool == "flight"
    assert record.action == "search_flights"
    assert record.status == StepStatus.COMPLETED.value
    assert record.step_id == "search"
    assert record.trace_id == "trace1"
    assert record.message is not None


def test_tool_history_records_every_step_in_full_plan_run() -> None:
    store = InMemoryStateStore()

    state, _ = run_chat(
        user_message="Book flights TIA to FRA on 2025-09-15",
        trace_id="trace1",
        store=store,
    )

    assert len(state.tool_history) == 3
    assert [record.step_id for record in state.tool_history] == ["search", "select", "booking"]
    assert all(record.trace_id == "trace1" for record in state.tool_history)
    assert all(record.message for record in state.tool_history)


def test_tool_history_survives_agent_state_roundtrip() -> None:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.user_message = "Book flights TIA to FRA on 2025-09-15"
    state.plan = build_default_flight_plan("Find flights")
    step = select_current_step(state)
    assert step is not None
    execute_step(state, step)

    restored = AgentState.model_validate_json(state.model_dump_json())

    assert len(restored.tool_history) == 1
    assert restored.tool_history[0].step_id == "search"
    assert restored.tool_history[0].message is not None
