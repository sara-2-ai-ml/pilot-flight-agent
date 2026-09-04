"""Coordinator tests — Phase 2.5."""

from unittest.mock import MagicMock

from app.agent.coordinator import (
    execute_step,
    execute_step_stub,
    find_next_executable_step_index,
    select_current_step,
)
from app.agent.planning import build_default_flight_plan
from app.agent.state import AgentState
from app.agent.workers.base import WorkerResult
from app.models.planning import PlanStatus, StepStatus, Worker


def test_select_current_step_picks_first_ready_step() -> None:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.plan = build_default_flight_plan("Find flights")

    step = select_current_step(state)

    assert step is not None
    assert step.id == "search"
    assert step.depends_on == []
    assert state.plan.current_step == 0
    assert state.plan.status == PlanStatus.IN_PROGRESS


def test_find_next_executable_step_waits_for_dependencies() -> None:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.plan = build_default_flight_plan("Find flights")
    state.plan.steps[0].status = StepStatus.COMPLETED

    index = find_next_executable_step_index(state)

    assert index == 1
    assert state.plan.steps[1].id == "select"


def test_select_current_step_returns_none_when_plan_is_empty() -> None:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")

    assert select_current_step(state) is None


def test_execute_step_marks_step_completed() -> None:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.user_message = "Book flights TIA to FRA on 2025-09-15"
    state.plan = build_default_flight_plan("Find flights")
    step = select_current_step(state)

    assert step is not None
    message, success = execute_step(state, step)

    assert success is True
    assert "Found 3 mock flights from TIA to FRA" in message
    assert step.status == StepStatus.COMPLETED
    assert len(state.tool_history) == 1
    assert state.tool_history[0].action == "search_flights"
    assert state.plan.status == PlanStatus.IN_PROGRESS


def test_execute_step_stub_alias_delegates_to_execute_step() -> None:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.user_message = "Book flights TIA to FRA on 2025-09-15"
    state.plan = build_default_flight_plan("Find flights")
    step = select_current_step(state)

    assert step is not None
    message, success = execute_step_stub(state, step)

    assert success is True
    assert "Found 3 mock flights from TIA to FRA" in message


def test_execute_step_delegates_flight_worker_for_flight_step() -> None:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.plan = build_default_flight_plan("Find flights")
    step = select_current_step(state)
    assert step is not None
    assert step.worker == Worker.FLIGHT

    mock_worker = MagicMock()
    mock_worker.execute.return_value = WorkerResult(
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


def test_execute_step_queues_booking_for_approval_instead_of_worker() -> None:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.plan = build_default_flight_plan("Find flights")
    state.plan.steps[0].status = StepStatus.COMPLETED
    state.plan.steps[1].status = StepStatus.COMPLETED
    state.flight_search.selected_option_id = "LH001"
    state.flight_search.origin = "TIA"
    state.flight_search.destination = "FRA"
    state.flight_search.date = "2025-09-15"
    step = select_current_step(state)
    assert step is not None
    assert step.worker == Worker.BOOKING

    mock_worker = MagicMock()
    mock_worker.execute.return_value = WorkerResult(
        message="Booking worker handled create_booking",
        success=True,
    )

    import app.agent.coordinator as coordinator

    original_get_worker = coordinator.get_worker
    coordinator.get_worker = lambda worker: mock_worker if worker == Worker.BOOKING else original_get_worker(worker)
    try:
        message, success = execute_step(state, step)
    finally:
        coordinator.get_worker = original_get_worker

    mock_worker.execute.assert_not_called()
    assert success is True
    assert "Booking approval required" in message
    assert state.pending_approval is not None
    assert state.pending_approval["action"] == "create_booking"
