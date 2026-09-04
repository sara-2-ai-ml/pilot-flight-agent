"""Clean state after approval denial — Phase 7.6."""

import sqlite3

from fastapi.testclient import TestClient

import pytest

from app.agent.approval_flow import ApprovalFlowError, cancel_pending_approval, run_cancel_approval
from app.agent.loop import run_chat
from app.agent.state import InMemoryStateStore, get_state_store
from app.config import Settings
from app.guardrails.approval import APPROVAL_CANCELLED_STATUS
from app.main import app
from app.models.booking import BookingState, BookingStatus
from app.models.planning import PlanStatus, StepStatus
from app.tools.booking_store import BookingStore


def _queue_booking_approval(
    tmp_path,
    *,
    store: InMemoryStateStore | None = None,
    conversation_id: str = "conv-deny-1",
) -> tuple[InMemoryStateStore, str, Settings]:
    db_path = tmp_path / "bookings.db"
    resolved_store = store or get_state_store()
    settings = Settings(flight_api_use_mock=True, booking_db_path=str(db_path))

    run_chat(
        user_message="Book flights TIA to FRA on 2025-09-15",
        trace_id="trace1",
        conversation_id=conversation_id,
        settings=settings,
        store=resolved_store,
    )

    return resolved_store, conversation_id, settings


def test_cancel_resets_booking_state_to_defaults(tmp_path) -> None:
    store, conversation_id, _settings = _queue_booking_approval(
        tmp_path,
        store=InMemoryStateStore(),
    )
    state = store.get(conversation_id)
    assert state is not None

    cancel_pending_approval(state)

    assert state.booking == BookingState()
    assert state.booking.status == BookingStatus.NONE
    assert state.pending_approval is None


def test_cancel_marks_booking_step_skipped_and_completes_plan(tmp_path) -> None:
    store, conversation_id, _settings = _queue_booking_approval(
        tmp_path,
        store=InMemoryStateStore(),
    )
    state = store.get(conversation_id)
    assert state is not None

    cancel_pending_approval(state)

    assert state.plan.steps[0].status == StepStatus.COMPLETED
    assert state.plan.steps[1].status == StepStatus.COMPLETED
    assert state.plan.steps[2].status == StepStatus.SKIPPED
    assert state.plan.status == PlanStatus.COMPLETED
    assert state.tool_history[-1].status == APPROVAL_CANCELLED_STATUS


def test_cancel_preserves_flight_search_results(tmp_path) -> None:
    store, conversation_id, _settings = _queue_booking_approval(
        tmp_path,
        store=InMemoryStateStore(),
    )
    state = store.get(conversation_id)
    assert state is not None

    cancel_pending_approval(state)

    assert state.flight_search.origin == "TIA"
    assert state.flight_search.destination == "FRA"
    assert len(state.flight_search.results) == 3
    assert state.flight_search.selected_option_id == "LH001"


def test_after_cancel_follow_up_chat_does_not_create_sqlite_record(tmp_path) -> None:
    store, conversation_id, settings = _queue_booking_approval(tmp_path)

    run_cancel_approval(
        conversation_id=conversation_id,
        trace_id="trace-cancel",
        store=store,
    )

    follow_up_state, follow_up_message = run_chat(
        user_message="Any updates?",
        trace_id="trace2",
        conversation_id=conversation_id,
        settings=settings,
        store=store,
    )

    assert "ready to help" in follow_up_message.lower()
    assert follow_up_state.pending_approval is None
    assert follow_up_state.booking.booking_id is None
    with sqlite3.connect(settings.booking_db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM bookings").fetchone()[0]
    assert count == 0


def test_get_pending_returns_null_after_cancel(tmp_path) -> None:
    store, conversation_id, _settings = _queue_booking_approval(
        tmp_path,
        conversation_id="conv-deny-pending",
    )
    client = TestClient(app)

    cancel = client.post("/approvals/cancel", json={"conversation_id": conversation_id})
    assert cancel.status_code == 200

    pending = client.get("/approvals/pending", params={"conversation_id": conversation_id})
    assert pending.status_code == 200
    assert pending.json()["pending_approval"] is None


def test_cancel_is_idempotent_error_when_already_cleared(tmp_path) -> None:
    store, conversation_id, _settings = _queue_booking_approval(
        tmp_path,
        store=InMemoryStateStore(),
    )
    state = store.get(conversation_id)
    assert state is not None

    cancel_pending_approval(state)

    with pytest.raises(ApprovalFlowError, match="No pending approval"):
        cancel_pending_approval(state)


def test_cancel_leaves_booking_store_empty(tmp_path) -> None:
    store, conversation_id, settings = _queue_booking_approval(
        tmp_path,
        store=InMemoryStateStore(),
    )
    state = store.get(conversation_id)
    assert state is not None

    cancel_pending_approval(state)

    booking_store = BookingStore(settings.booking_db_path)
    with sqlite3.connect(settings.booking_db_path) as conn:
        rows = conn.execute("SELECT booking_id FROM bookings").fetchall()
    assert rows == []
