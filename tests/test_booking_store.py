"""Booking store tests — Phase 5.5."""

import pytest

from app.models.booking import BookingRecord, BookingStatus
from app.tools.booking_store import BookingStore, BookingStoreError


@pytest.fixture
def store(tmp_path) -> BookingStore:
    return BookingStore(str(tmp_path / "bookings.db"))


def _sample_record(*, booking_id: str = "BK-TEST001") -> BookingRecord:
    return BookingRecord(
        booking_id=booking_id,
        conversation_id="conv1",
        flight_id="LH001",
        passenger="Ana Krasniqi",
        status=BookingStatus.PENDING,
        created_at="2025-09-15T10:00:00+00:00",
    )


def test_create_and_get_booking(store: BookingStore) -> None:
    record = _sample_record()
    store.create(record)

    loaded = store.get("BK-TEST001")

    assert loaded == record


def test_create_rejects_duplicate_booking_id(store: BookingStore) -> None:
    store.create(_sample_record())

    with pytest.raises(BookingStoreError, match="already exists"):
        store.create(_sample_record())


def test_get_returns_none_for_missing_booking(store: BookingStore) -> None:
    assert store.get("BK-MISSING") is None


def test_cancel_marks_booking_as_cancelled(store: BookingStore) -> None:
    store.create(_sample_record())

    cancelled = store.cancel("BK-TEST001")

    assert cancelled is not None
    assert cancelled.status == BookingStatus.CANCELLED
    assert store.get("BK-TEST001") == cancelled


def test_cancel_returns_none_for_missing_booking(store: BookingStore) -> None:
    assert store.cancel("BK-MISSING") is None


def test_cancel_is_idempotent_for_already_cancelled_booking(store: BookingStore) -> None:
    store.create(_sample_record())
    first = store.cancel("BK-TEST001")
    second = store.cancel("BK-TEST001")

    assert first == second
    assert second is not None
    assert second.status == BookingStatus.CANCELLED
