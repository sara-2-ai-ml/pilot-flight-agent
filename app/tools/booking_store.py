"""SQLite booking store — create, get, cancel bookings."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.models.booking import (
    BookingAuditAction,
    BookingAuditRecord,
    BookingRecord,
    BookingStatus,
)
from app.tools.booking_audit import (
    BookingAuditContext,
    audit_context_for_system,
    build_booking_audit_record,
    log_booking_audit,
)


class BookingStoreError(Exception):
    """Raised when a booking store operation fails."""


class BookingStore:
    """Local SQLite persistence for booking records."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _table_columns(self, conn: sqlite3.Connection) -> set[str]:
        rows = conn.execute("PRAGMA table_info(bookings)").fetchall()
        return {str(row["name"]) for row in rows}

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS bookings (
                    booking_id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    flight_id TEXT NOT NULL,
                    passenger TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    idempotency_key TEXT
                )
                """
            )
            columns = self._table_columns(conn)
            if "idempotency_key" not in columns:
                conn.execute("ALTER TABLE bookings ADD COLUMN idempotency_key TEXT")
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_bookings_idempotency_key
                ON bookings(idempotency_key)
                WHERE idempotency_key IS NOT NULL
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS booking_audit (
                    audit_id TEXT PRIMARY KEY,
                    action TEXT NOT NULL,
                    booking_id TEXT NOT NULL,
                    conversation_id TEXT,
                    flight_id TEXT,
                    passenger TEXT,
                    actor TEXT NOT NULL,
                    trace_id TEXT,
                    performed_at TEXT NOT NULL,
                    detail TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_booking_audit_booking_id
                ON booking_audit(booking_id)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_booking_audit_conversation_id
                ON booking_audit(conversation_id)
                """
            )

    def _resolve_audit_context(
        self,
        record: BookingRecord,
        audit_context: BookingAuditContext | None,
    ) -> BookingAuditContext:
        if audit_context is not None:
            return audit_context
        return BookingAuditContext(
            actor=record.conversation_id,
            trace_id=None,
            source="booking_store",
        )

    def _append_audit(
        self,
        *,
        action: BookingAuditAction,
        record: BookingRecord,
        audit_context: BookingAuditContext | None = None,
        detail: str | None = None,
    ) -> BookingAuditRecord:
        audit = build_booking_audit_record(
            action=action,
            record=record,
            context=self._resolve_audit_context(record, audit_context),
            detail=detail,
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO booking_audit (
                    audit_id,
                    action,
                    booking_id,
                    conversation_id,
                    flight_id,
                    passenger,
                    actor,
                    trace_id,
                    performed_at,
                    detail
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    audit.audit_id,
                    audit.action.value,
                    audit.booking_id,
                    audit.conversation_id,
                    audit.flight_id,
                    audit.passenger,
                    audit.actor,
                    audit.trace_id,
                    audit.performed_at,
                    audit.detail,
                ),
            )
        log_booking_audit(audit)
        return audit

    def list_audit(
        self,
        *,
        booking_id: str | None = None,
        conversation_id: str | None = None,
    ) -> list[BookingAuditRecord]:
        """Return audit entries filtered by booking or conversation."""
        clauses: list[str] = []
        params: list[str] = []
        if booking_id is not None:
            clauses.append("booking_id = ?")
            params.append(booking_id)
        if conversation_id is not None:
            clauses.append("conversation_id = ?")
            params.append(conversation_id)

        query = "SELECT * FROM booking_audit"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY performed_at ASC"

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_audit(row) for row in rows]

    def create(
        self,
        record: BookingRecord,
        *,
        audit_context: BookingAuditContext | None = None,
    ) -> BookingRecord:
        """Insert a new booking record."""
        with self._connect() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO bookings (
                        booking_id,
                        conversation_id,
                        flight_id,
                        passenger,
                        status,
                        created_at,
                        idempotency_key
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.booking_id,
                        record.conversation_id,
                        record.flight_id,
                        record.passenger,
                        record.status.value,
                        record.created_at,
                        record.idempotency_key,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise BookingStoreError(
                    f"Booking {record.booking_id} already exists.",
                ) from exc
        self._append_audit(
            action=BookingAuditAction.CREATE,
            record=record,
            audit_context=audit_context,
        )
        return record

    def get_by_idempotency_key(self, idempotency_key: str) -> BookingRecord | None:
        """Fetch one booking by idempotency key."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM bookings WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def create_idempotent(
        self,
        record: BookingRecord,
        *,
        idempotency_key: str,
        audit_context: BookingAuditContext | None = None,
    ) -> tuple[BookingRecord, bool]:
        """Create a booking once for an idempotency key and return replays safely."""
        existing = self.get_by_idempotency_key(idempotency_key)
        if existing is not None:
            return existing, False

        stored = record.model_copy(update={"idempotency_key": idempotency_key})
        try:
            self.create(stored, audit_context=audit_context)
        except BookingStoreError:
            by_key = self.get_by_idempotency_key(idempotency_key)
            if by_key is not None:
                return by_key, False
            by_id = self.get(record.booking_id)
            if by_id is not None:
                return by_id, False
            raise

        return stored, True

    def get(self, booking_id: str) -> BookingRecord | None:
        """Fetch one booking by id."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM bookings WHERE booking_id = ?",
                (booking_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def cancel(
        self,
        booking_id: str,
        *,
        audit_context: BookingAuditContext | None = None,
    ) -> BookingRecord | None:
        """Mark a booking as cancelled."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM bookings WHERE booking_id = ?",
                (booking_id,),
            ).fetchone()
            if row is None:
                return None
            if row["status"] == BookingStatus.CANCELLED.value:
                return self._row_to_record(row)
            conn.execute(
                "UPDATE bookings SET status = ? WHERE booking_id = ?",
                (BookingStatus.CANCELLED.value, booking_id),
            )
            updated = conn.execute(
                "SELECT * FROM bookings WHERE booking_id = ?",
                (booking_id,),
            ).fetchone()
        record = self._row_to_record(updated) if updated is not None else None
        if record is not None:
            context = audit_context or audit_context_for_system(source="booking_store")
            self._append_audit(
                action=BookingAuditAction.CANCEL,
                record=record,
                audit_context=context,
            )
        return record

    @staticmethod
    def utc_now_iso() -> str:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    @staticmethod
    def _row_to_audit(row: sqlite3.Row) -> BookingAuditRecord:
        return BookingAuditRecord(
            audit_id=row["audit_id"],
            action=BookingAuditAction(row["action"]),
            booking_id=row["booking_id"],
            conversation_id=row["conversation_id"],
            flight_id=row["flight_id"],
            passenger=row["passenger"],
            actor=row["actor"],
            trace_id=row["trace_id"],
            performed_at=row["performed_at"],
            detail=row["detail"],
        )

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> BookingRecord:
        keys = row.keys()
        return BookingRecord(
            booking_id=row["booking_id"],
            conversation_id=row["conversation_id"],
            flight_id=row["flight_id"],
            passenger=row["passenger"],
            status=BookingStatus(row["status"]),
            created_at=row["created_at"],
            idempotency_key=row["idempotency_key"] if "idempotency_key" in keys else None,
        )
