"""Booking idempotency tests — Phase 9.4."""

import sqlite3

import pytest

from app.agent.state import AgentState
from app.core.idempotency import build_booking_idempotency_key
from app.mcp.servers.booking_handlers import create_booking_handler
from app.models.booking import BookingRecord, BookingStatus
from app.tools.booking_service import BookingService
from app.tools.booking_store import BookingStore


def test_build_booking_idempotency_key_is_deterministic() -> None:
    first = build_booking_idempotency_key(
        conversation_id="conv1",
        flight_id="LH001",
    )
    second = build_booking_idempotency_key(
        conversation_id="conv1",
        flight_id="LH001",
    )

    assert first == second
    assert len(first) == 64


def test_create_idempotent_returns_existing_booking(store: BookingStore) -> None:
    key = build_booking_idempotency_key(conversation_id="conv1", flight_id="LH001")
    record = BookingRecord(
        booking_id="BK-TEST001",
        conversation_id="conv1",
        flight_id="LH001",
        passenger="Ana Krasniqi",
        status=BookingStatus.PENDING,
        created_at="2025-09-15T10:00:00+00:00",
    )

    created, was_created = store.create_idempotent(record, idempotency_key=key)
    replayed, was_replayed = store.create_idempotent(record, idempotency_key=key)

    assert was_created is True
    assert was_replayed is False
    assert replayed == created
    assert replayed.idempotency_key == key


def test_create_booking_handler_retries_create_one_sqlite_row(tmp_path) -> None:
    db_path = tmp_path / "bookings.db"
    store = BookingStore(str(db_path))

    first = create_booking_handler(
        conversation_id="conv1",
        flight_id="LH001",
        passenger="Ana Krasniqi",
        store=store,
    )
    second = create_booking_handler(
        conversation_id="conv1",
        flight_id="LH001",
        passenger="Ana Krasniqi",
        store=store,
    )

    assert first["found"] is True
    assert first["idempotent_replay"] is False
    assert second["found"] is True
    assert second["idempotent_replay"] is True
    assert second["booking_id"] == first["booking_id"]

    with sqlite3.connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM bookings").fetchone()[0]

    assert count == 1


def test_booking_service_retry_leaves_single_row(tmp_path) -> None:
    store = BookingStore(str(tmp_path / "bookings.db"))
    service = BookingService(store=store)
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.user_message = "Book flight LH001 for Ana Krasniqi"
    state.flight_search.selected_option_id = "LH001"

    first = service.create_booking(state)
    second = service.create_booking(state)

    assert first.success is True
    assert second.success is True
    assert "Returning existing booking" in second.message

    with sqlite3.connect(tmp_path / "bookings.db") as conn:
        count = conn.execute("SELECT COUNT(*) FROM bookings").fetchone()[0]

    assert count == 1


@pytest.fixture
def store(tmp_path) -> BookingStore:
    return BookingStore(str(tmp_path / "bookings.db"))
