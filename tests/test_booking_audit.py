"""Booking audit trail tests — Phase 10.4."""

import io
import json
import logging

import pytest

from app.agent.state import AgentState
from app.core.logging import StructuredFormatter, setup_logging
from app.core.tracing import set_trace_id
from app.mcp.servers.booking_handlers import cancel_booking_handler, create_booking_handler
from app.models.booking import BookingAuditAction, BookingRecord, BookingStatus
from app.tools.booking_audit import audit_context_from_state
from app.tools.booking_service import BookingService
from app.tools.booking_store import BookingStore


@pytest.fixture
def store(tmp_path) -> BookingStore:
    return BookingStore(str(tmp_path / "bookings.db"))


@pytest.fixture
def log_capture() -> io.StringIO:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(StructuredFormatter())

    app_logger = logging.getLogger("app")
    app_logger.handlers = [handler]
    app_logger.setLevel(logging.INFO)
    app_logger.propagate = False

    setup_logging("INFO")
    yield stream

    app_logger.handlers = []
    setup_logging("INFO")


def _sample_record(*, booking_id: str = "BK-TEST001") -> BookingRecord:
    return BookingRecord(
        booking_id=booking_id,
        conversation_id="conv1",
        flight_id="LH001",
        passenger="Ana Krasniqi",
        status=BookingStatus.PENDING,
        created_at="2025-09-15T10:00:00+00:00",
    )


def test_create_records_audit_with_actor_and_booking_details(store: BookingStore) -> None:
    set_trace_id("trace-audit-1")
    record = _sample_record()

    store.create(
        record,
        audit_context=audit_context_from_state(
            AgentState.new(conversation_id="conv1", trace_id="trace-audit-1")
        ),
    )

    audits = store.list_audit(booking_id="BK-TEST001")

    assert len(audits) == 1
    assert audits[0].action == BookingAuditAction.CREATE
    assert audits[0].actor == "conv1"
    assert audits[0].trace_id == "trace-audit-1"
    assert audits[0].flight_id == "LH001"
    assert audits[0].passenger == "Ana Krasniqi"
    assert audits[0].performed_at


def test_cancel_records_audit_entry(store: BookingStore) -> None:
    store.create(_sample_record())

    store.cancel("BK-TEST001")

    audits = store.list_audit(booking_id="BK-TEST001")

    assert len(audits) == 2
    assert audits[0].action == BookingAuditAction.CREATE
    assert audits[1].action == BookingAuditAction.CANCEL
    assert audits[1].booking_id == "BK-TEST001"


def test_idempotent_replay_does_not_duplicate_create_audit(store: BookingStore) -> None:
    record = _sample_record()
    key = "idem-key-1"

    store.create_idempotent(record, idempotency_key=key)
    store.create_idempotent(record, idempotency_key=key)

    assert len(store.list_audit(booking_id="BK-TEST001")) == 1


def test_cancel_idempotent_does_not_duplicate_cancel_audit(store: BookingStore) -> None:
    store.create(_sample_record())
    store.cancel("BK-TEST001")
    store.cancel("BK-TEST001")

    cancel_entries = [
        audit
        for audit in store.list_audit(booking_id="BK-TEST001")
        if audit.action == BookingAuditAction.CANCEL
    ]
    assert len(cancel_entries) == 1


def test_booking_service_create_writes_audit(store: BookingStore) -> None:
    service = BookingService(store=store)
    state = AgentState.new(conversation_id="conv-service", trace_id="trace-service")
    state.user_message = "Book flight LH001 for Ana Krasniqi"
    state.flight_search.selected_option_id = "LH001"

    result = service.create_booking(state)

    assert result.success is True
    audits = store.list_audit(conversation_id="conv-service")
    assert len(audits) == 1
    assert audits[0].action == BookingAuditAction.CREATE
    assert audits[0].actor == "conv-service"
    assert audits[0].trace_id == "trace-service"


def test_mcp_handlers_record_create_and_cancel_audit(store: BookingStore) -> None:
    created = create_booking_handler(
        conversation_id="conv-mcp",
        flight_id="LH001",
        passenger="Ana Krasniqi",
        store=store,
    )
    cancelled = cancel_booking_handler(
        booking_id=created["booking_id"],
        store=store,
    )

    assert cancelled["cancelled"] is True
    audits = store.list_audit(booking_id=created["booking_id"])
    assert [audit.action for audit in audits] == [
        BookingAuditAction.CREATE,
        BookingAuditAction.CANCEL,
    ]
    assert audits[0].actor == "conv-mcp"
    assert audits[1].actor == "mcp"


def test_booking_audit_emits_structured_log(store: BookingStore, log_capture: io.StringIO) -> None:
    store.create(_sample_record())

    records = [json.loads(line) for line in log_capture.getvalue().strip().splitlines()]
    audit_log = next(record for record in records if record.get("event") == "booking_audit")

    assert audit_log["action"] == "create"
    assert audit_log["booking_id"] == "BK-TEST001"
    assert audit_log["actor"] == "conv1"
    assert audit_log["flight_id"] == "LH001"
