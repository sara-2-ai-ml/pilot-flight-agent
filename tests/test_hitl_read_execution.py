"""READ tool direct execution tests — Phase 7.2."""

from unittest.mock import MagicMock

import pytest

from app.agent.coordinator import execute_step, select_current_step
from app.agent.loop import run_chat
from app.agent.planning import build_default_flight_plan
from app.agent.state import AgentState, InMemoryStateStore
from app.guardrails.permissions import executes_directly
from app.models.planning import StepStatus, Worker


@pytest.mark.parametrize(
    ("worker", "action"),
    [
        (Worker.FLIGHT, "search_flights"),
        (Worker.FLIGHT, "validate_options"),
    ],
)
def test_read_worker_actions_execute_directly(worker: Worker, action: str) -> None:
    assert executes_directly(worker=worker, action=action) is True


def test_write_worker_actions_do_not_execute_directly() -> None:
    assert executes_directly(worker=Worker.BOOKING, action="create_booking") is False


def test_execute_step_runs_search_flights_without_pending_approval() -> None:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.user_message = "Book flights TIA to FRA on 2025-09-15"
    state.plan = build_default_flight_plan("Find flights")
    step = select_current_step(state)

    assert step is not None
    assert step.action == "search_flights"

    message, success = execute_step(state, step)

    assert success is True
    assert "Found 3 mock flights from TIA to FRA" in message
    assert state.pending_approval is None
    assert len(state.flight_search.results) == 3


def test_read_tools_run_even_when_pending_approval_is_set() -> None:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.user_message = "Book flights TIA to FRA on 2025-09-15"
    state.plan = build_default_flight_plan("Find flights")
    state.pending_approval = {
        "action": "create_booking",
        "flight_id": "LH001",
    }
    step = select_current_step(state)

    assert step is not None

    message, success = execute_step(state, step)

    assert success is True
    assert "Found 3 mock flights" in message
    assert state.pending_approval["action"] == "create_booking"


def test_execute_step_read_path_delegates_to_worker_without_approval_gate() -> None:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.plan = build_default_flight_plan("Find flights")
    step = select_current_step(state)
    assert step is not None

    mock_worker = MagicMock()
    mock_worker.execute.return_value = MagicMock(
        message="Flight worker handled search_flights",
        success=True,
    )

    import app.agent.coordinator as coordinator

    original_get_worker = coordinator.get_worker
    coordinator.get_worker = lambda worker: mock_worker if worker == Worker.FLIGHT else original_get_worker(worker)
    try:
        message, success = execute_step(state, step)
    finally:
        coordinator.get_worker = original_get_worker

    mock_worker.execute.assert_called_once_with("search_flights", state)
    assert success is True
    assert message == "Flight worker handled search_flights"
    assert state.pending_approval is None


def test_run_chat_full_plan_sets_pending_approval_after_read_steps() -> None:
    store = InMemoryStateStore()

    state, message = run_chat(
        user_message="Book flights TIA to FRA on 2025-09-15",
        trace_id="trace1",
        conversation_id="conv-hitl-read-1",
        store=store,
    )

    assert "Found 3 mock flights from TIA to FRA" in message
    assert "Booking approval required" in message
    assert state.pending_approval is not None
    assert state.plan.steps[0].status == StepStatus.COMPLETED
    assert state.plan.steps[0].action == "search_flights"
