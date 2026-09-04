"""Backward-compatible re-exports — normalization lives in app.models.flight."""

from app.models.flight import (
    normalize_flight_status_payload,
    normalize_lufthansa_payload,
    normalize_schedule_payload,
)

normalize_schedule_response = normalize_schedule_payload
normalize_flight_status_response = normalize_flight_status_payload

__all__ = [
    "normalize_flight_status_response",
    "normalize_lufthansa_payload",
    "normalize_schedule_response",
]
