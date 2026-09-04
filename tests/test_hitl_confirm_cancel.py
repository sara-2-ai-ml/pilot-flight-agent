"""Approval confirm/cancel tests — Phase 7.4."""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.agent.approval_flow import (
    ApprovalFlowError,
    cancel_pending_approval,
    confirm_pending_approval,
    run_cancel_approval,
    run_confirm_approval,
)
from app.agent.loop import run_chat
from app.agent.state import AgentState, InMemoryStateStore, get_state_store
from app.config import Settings
from app.main import app
from app.models.booking import BookingStatus
from app.models.planning import PlanStatus, StepStatus
from app.tools.booking_service import mock_booking_id
from app.tools.booking_store import BookingStore


def _queue_booking_approval(
    tmp_path,
    *,
    store: InMemoryStateStore | None = None,
) -> tuple[InMemoryStateStore, str, Settings]:
    db_path = tmp_path / "bookings.db"
    resolved_store = store or get_state_store()
    settings = Settings(flight_api_use_mock=True, booking_db_path=str(db_path))
    conversation_id = "conv-approval-1"

    run_chat(
        user_message="Book flights TIA to FRA on 2025-09-15",
        trace_id="trace1",
        conversation_id=conversation_id,
        settings=settings,
        store=resolved_store,
    )

    state = resolved_store.get(conversation_id)
    assert state is not None
    assert state.pending_approval is not None
    return resolved_store, conversation_id, settings


def test_confirm_pending_approval_creates_booking(tmp_path) -> None:
    store, conversation_id, settings = _queue_booking_approval(
        tmp_path,
        store=InMemoryStateStore(),
    )
    state = store.get(conversation_id)
    assert state is not None

    message, success = confirm_pending_approval(state, settings=settings)

    assert success is True
    assert "Created booking BK-" in message
    assert state.pending_approval is None
    assert state.booking.booking_id is not None
    assert state.booking.status == BookingStatus.PENDING
    assert state.plan.status == PlanStatus.COMPLETED
    assert state.plan.steps[2].status == StepStatus.COMPLETED
    assert BookingStore(settings.booking_db_path).get(state.booking.booking_id) is not None


def test_cancel_pending_approval_clears_state_without_db_write(tmp_path) -> None:
    store, conversation_id, settings = _queue_booking_approval(
        tmp_path,
        store=InMemoryStateStore(),
    )
    state = store.get(conversation_id)
    assert state is not None

    message, success = cancel_pending_approval(state)

    assert success is True
    assert message == "Booking request cancelled."
    assert state.pending_approval is None
    assert state.booking.booking_id is None
    assert state.plan.steps[2].status == StepStatus.SKIPPED
    assert state.plan.status == PlanStatus.COMPLETED
    with sqlite3.connect(settings.booking_db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM bookings").fetchone()[0]
    assert count == 0


def test_confirm_raises_when_no_pending_approval() -> None:
    store = InMemoryStateStore()
    settings = Settings(flight_api_use_mock=True)
    store.save(AgentState.new(conversation_id="conv-empty", trace_id="trace1"))
    state = store.get("conv-empty")
    assert state is not None

    with pytest.raises(ApprovalFlowError, match="No pending approval"):
        confirm_pending_approval(state, settings=settings)


def test_confirm_endpoint_creates_booking(tmp_path) -> None:
    store, conversation_id, settings = _queue_booking_approval(tmp_path)
    client = TestClient(app)

    response = client.post("/approvals/confirm", json={"conversation_id": conversation_id})

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["conversation_id"] == conversation_id
    assert "Created booking BK-" in body["message"]

    state = store.get(conversation_id)
    assert state is not None
    assert state.pending_approval is None
    assert state.booking.booking_id == mock_booking_id(
        conversation_id=conversation_id,
        flight_id="LH001",
    )


def test_cancel_endpoint_aborts_booking(tmp_path) -> None:
    store, conversation_id, settings = _queue_booking_approval(tmp_path)
    client = TestClient(app)

    response = client.post("/approvals/cancel", json={"conversation_id": conversation_id})

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["message"] == "Booking request cancelled."

    state = store.get(conversation_id)
    assert state is not None
    assert state.pending_approval is None
    assert state.booking.booking_id is None


def test_confirm_endpoint_returns_404_for_missing_conversation() -> None:
    client = TestClient(app)

    response = client.post("/approvals/confirm", json={"conversation_id": "missing-conv"})

    assert response.status_code == 404


def test_run_confirm_approval_persists_state(tmp_path) -> None:
    store, conversation_id, settings = _queue_booking_approval(
        tmp_path,
        store=InMemoryStateStore(),
    )

    state, message, success = run_confirm_approval(
        conversation_id=conversation_id,
        trace_id="trace-confirm",
        settings=settings,
        store=store,
    )

    assert success is True
    assert "Created booking BK-" in message
    persisted = store.get(conversation_id)
    assert persisted is not None
    assert persisted.booking.booking_id == state.booking.booking_id
    assert persisted.pending_approval is None


def test_run_cancel_approval_persists_state(tmp_path) -> None:
    store, conversation_id, _settings = _queue_booking_approval(
        tmp_path,
        store=InMemoryStateStore(),
    )

    state, message, success = run_cancel_approval(
        conversation_id=conversation_id,
        trace_id="trace-cancel",
        store=store,
    )

    assert success is True
    assert message == "Booking request cancelled."
    persisted = store.get(conversation_id)
    assert persisted is not None
    assert persisted.pending_approval is None
    assert persisted.plan.steps[2].status == StepStatus.SKIPPED
    assert persisted.plan.status == PlanStatus.COMPLETED
