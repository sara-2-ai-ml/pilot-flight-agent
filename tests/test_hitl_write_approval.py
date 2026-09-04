"""WRITE tool approval queue tests — Phase 7.3."""

import sqlite3
from unittest.mock import MagicMock

from app.agent.coordinator import execute_step, select_current_step
from app.agent.loop import run_chat
from app.agent.planning import build_default_flight_plan
from app.agent.state import AgentState, InMemoryStateStore
from app.config import Settings
from app.guardrails.approval import APPROVAL_STATUS, build_create_booking_approval
from app.models.booking import BookingStatus
from app.models.planning import PlanStatus, StepStatus, Worker


def test_build_create_booking_approval_includes_flight_context() -> None:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.user_message = "Book flight for Ana Krasniqi"
    state.flight_search.selected_option_id = "LH001"
    state.flight_search.origin = "TIA"
    state.flight_search.destination = "FRA"
    state.flight_search.date = "2025-09-15"
    step = build_default_flight_plan("Book").steps[2]

    payload = build_create_booking_approval(state, step)

    assert payload["action"] == "create_booking"
    assert payload["passenger"] == "Ana Krasniqi"
    assert payload["route"]["origin"] == "TIA"
    assert payload["route"]["destination"] == "FRA"
    assert payload["flight"]["id"] == "LH001"


def test_execute_step_queues_create_booking_without_calling_worker() -> None:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.user_message = "Book flight for Ana Krasniqi"
    state.plan = build_default_flight_plan("Find flights")
    state.plan.steps[0].status = StepStatus.COMPLETED
    state.plan.steps[1].status = StepStatus.COMPLETED
    state.flight_search.selected_option_id = "LH001"
    state.flight_search.origin = "TIA"
    state.flight_search.destination = "FRA"
    state.flight_search.date = "2025-09-15"
    step = select_current_step(state)
    assert step is not None

    mock_worker = MagicMock()
    import app.agent.coordinator as coordinator

    original_get_worker = coordinator.get_worker
    coordinator.get_worker = lambda worker: mock_worker if worker == Worker.BOOKING else original_get_worker(worker)
    try:
        message, success = execute_step(state, step)
    finally:
        coordinator.get_worker = original_get_worker

    mock_worker.execute.assert_not_called()
    assert success is True
    assert state.pending_approval is not None
    assert state.pending_approval["action"] == "create_booking"
    assert state.pending_approval["flight"]["id"] == "LH001"
    assert state.pending_approval["route"]["origin"] == "TIA"
    assert state.booking.booking_id is None
    assert step.status == StepStatus.IN_PROGRESS
    assert state.tool_history[-1].status == APPROVAL_STATUS


def test_run_chat_queues_booking_without_sqlite_write(tmp_path) -> None:
    db_path = tmp_path / "bookings.db"
    store = InMemoryStateStore()
    settings = Settings(flight_api_use_mock=True, booking_db_path=str(db_path))

    state, message = run_chat(
        user_message="Book flights TIA to FRA on 2025-09-15",
        trace_id="trace1",
        conversation_id="conv-hitl-write-1",
        settings=settings,
        store=store,
    )

    assert "Booking approval required" in message
    assert state.pending_approval is not None
    assert state.pending_approval["flight"]["id"] == "LH001"
    assert state.booking.booking_id is None
    assert state.booking.status == BookingStatus.NONE
    assert state.plan.status == PlanStatus.IN_PROGRESS
    assert state.plan.steps[2].status == StepStatus.IN_PROGRESS
    with sqlite3.connect(str(db_path)) as conn:
        count = conn.execute("SELECT COUNT(*) FROM bookings").fetchone()[0]
    assert count == 0


def test_run_chat_leaves_plan_in_progress_until_booking_confirmed() -> None:
    store = InMemoryStateStore()

    state, _ = run_chat(
        user_message="Book flights TIA to FRA on 2025-09-15",
        trace_id="trace1",
        conversation_id="conv-hitl-write-2",
        store=store,
    )

    assert state.plan.steps[0].status == StepStatus.COMPLETED
    assert state.plan.steps[1].status == StepStatus.COMPLETED
    assert state.plan.steps[2].status == StepStatus.IN_PROGRESS
    assert state.plan.status == PlanStatus.IN_PROGRESS
