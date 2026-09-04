"""Booking HITL + idempotency integration tests — Phase 11.6."""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.agent.approval_flow import (
    ApprovalFlowError,
    cancel_pending_approval,
    confirm_pending_approval,
    run_confirm_approval,
)
from app.agent.loop import run_chat
from app.agent.state import InMemoryStateStore
from app.config import Settings
from app.core.idempotency import build_booking_idempotency_key
from app.main import create_app
from app.models.booking import BookingStatus
from app.models.planning import PlanStatus, StepStatus
from app.tools.booking_service import BookingService
from app.tools.booking_store import BookingStore


def _booking_count(db_path: str) -> int:
    from pathlib import Path

    if not Path(db_path).exists():
        return 0
    with sqlite3.connect(db_path) as conn:
        try:
            return int(conn.execute("SELECT COUNT(*) FROM bookings").fetchone()[0])
        except sqlite3.OperationalError:
            return 0


def _queue_booking_approval(
    tmp_path,
    *,
    store: InMemoryStateStore | None = None,
    conversation_id: str = "conv-booking-hitl",
) -> tuple[InMemoryStateStore, str, Settings]:
    db_path = tmp_path / "bookings.db"
    resolved_store = store or InMemoryStateStore()
    settings = Settings(flight_api_use_mock=True, booking_db_path=str(db_path))

    run_chat(
        user_message="Book flights TIA to FRA on 2025-09-15",
        trace_id="trace-hitl",
        conversation_id=conversation_id,
        settings=settings,
        store=resolved_store,
    )

    state = resolved_store.get(conversation_id)
    assert state is not None
    assert state.pending_approval is not None
    assert state.pending_approval["action"] == "create_booking"
    assert _booking_count(settings.booking_db_path) == 0
    return resolved_store, conversation_id, settings


def test_hitl_queues_booking_without_writing_to_store(tmp_path) -> None:
    store, conversation_id, settings = _queue_booking_approval(tmp_path)
    state = store.get(conversation_id)

    assert state is not None
    assert state.plan.steps[2].status == StepStatus.IN_PROGRESS
    assert state.booking.booking_id is None
    assert _booking_count(settings.booking_db_path) == 0


def test_hitl_confirm_creates_one_booking_row(tmp_path) -> None:
    store, conversation_id, settings = _queue_booking_approval(
        tmp_path,
        store=InMemoryStateStore(),
    )
    state = store.get(conversation_id)
    assert state is not None

    message, success = confirm_pending_approval(state, settings=settings)
    store.save(state)

    assert success is True
    assert "Created booking BK-" in message
    assert state.pending_approval is None
    assert state.booking.status == BookingStatus.PENDING
    assert state.plan.status == PlanStatus.COMPLETED
    assert _booking_count(settings.booking_db_path) == 1
    assert BookingStore(settings.booking_db_path).get(state.booking.booking_id) is not None


def test_hitl_cancel_aborts_without_booking_row(tmp_path) -> None:
    store, conversation_id, settings = _queue_booking_approval(
        tmp_path,
        store=InMemoryStateStore(),
    )
    state = store.get(conversation_id)
    assert state is not None

    message, success = cancel_pending_approval(state)
    store.save(state)

    assert success is True
    assert message == "Booking request cancelled."
    assert state.pending_approval is None
    assert state.booking.booking_id is None
    assert state.plan.steps[2].status == StepStatus.SKIPPED
    assert state.plan.status == PlanStatus.COMPLETED
    assert _booking_count(settings.booking_db_path) == 0


def test_hitl_confirm_is_idempotent_when_booking_retried(tmp_path) -> None:
    store, conversation_id, settings = _queue_booking_approval(
        tmp_path,
        store=InMemoryStateStore(),
    )
    state = store.get(conversation_id)
    assert state is not None

    first_message, first_success = confirm_pending_approval(state, settings=settings)
    assert first_success is True
    booking_id = state.booking.booking_id
    assert booking_id is not None

    service = BookingService(store=BookingStore(settings.booking_db_path), settings=settings)
    retry = service.create_booking(state)

    assert retry.success is True
    assert "Returning existing booking" in retry.message
    assert state.booking.booking_id == booking_id
    assert _booking_count(settings.booking_db_path) == 1


def test_hitl_confirm_uses_stable_idempotency_key(tmp_path) -> None:
    store, conversation_id, settings = _queue_booking_approval(
        tmp_path,
        store=InMemoryStateStore(),
    )
    state = store.get(conversation_id)
    assert state is not None

    confirm_pending_approval(state, settings=settings)

    expected_key = build_booking_idempotency_key(
        conversation_id=conversation_id,
        flight_id="LH001",
    )
    stored = BookingStore(settings.booking_db_path).get(state.booking.booking_id)

    assert stored is not None
    assert stored.idempotency_key == expected_key


def test_hitl_http_chat_and_confirm_flow(tmp_path) -> None:
    db_path = tmp_path / "bookings.db"
    settings = Settings(flight_api_use_mock=True, booking_db_path=str(db_path))
    client = TestClient(create_app(settings))

    chat = client.post(
        "/chat",
        json={"message": "Book flights TIA to FRA on 2025-09-15", "conversation_id": "conv-http-hitl"},
    )
    assert chat.status_code == 200
    chat_body = chat.json()
    assert chat_body["pending_approval"] is not None
    assert _booking_count(str(db_path)) == 0

    confirm = client.post("/approvals/confirm", json={"conversation_id": "conv-http-hitl"})
    assert confirm.status_code == 200
    confirm_body = confirm.json()
    assert confirm_body["success"] is True
    assert "Created booking BK-" in confirm_body["message"]
    assert confirm_body["conversation_id"] == "conv-http-hitl"
    assert _booking_count(str(db_path)) == 1


def test_hitl_second_confirm_fails_after_successful_booking(tmp_path) -> None:
    store, conversation_id, settings = _queue_booking_approval(
        tmp_path,
        store=InMemoryStateStore(),
    )

    state, message, success = run_confirm_approval(
        conversation_id=conversation_id,
        trace_id="trace-confirm-1",
        settings=settings,
        store=store,
    )
    assert success is True
    assert state.pending_approval is None

    with pytest.raises(ApprovalFlowError, match="No pending approval"):
        confirm_pending_approval(store.get(conversation_id), settings=settings)


def test_hitl_cancel_then_follow_up_chat_does_not_create_booking(tmp_path) -> None:
    store, conversation_id, settings = _queue_booking_approval(
        tmp_path,
        store=InMemoryStateStore(),
    )
    state = store.get(conversation_id)
    assert state is not None
    cancel_pending_approval(state)
    store.save(state)

    follow_up_state, follow_up_message = run_chat(
        user_message="Try booking again please",
        trace_id="trace-follow-up",
        conversation_id=conversation_id,
        settings=settings,
        store=store,
    )

    assert _booking_count(settings.booking_db_path) == 0
    assert follow_up_state.booking.booking_id is None
    assert "Created booking BK-" not in follow_up_message
