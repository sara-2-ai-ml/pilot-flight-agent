"""Idempotency helpers for external side effects."""

from __future__ import annotations

import hashlib


def build_booking_idempotency_key(
    *,
    conversation_id: str,
    flight_id: str,
    action: str = "create_booking",
) -> str:
    """Return a deterministic idempotency key for one booking request."""
    material = f"{action}:{conversation_id}:{flight_id}"
    return hashlib.sha256(material.encode()).hexdigest()
