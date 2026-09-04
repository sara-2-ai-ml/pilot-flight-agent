"""Lufthansa MCP tool handlers — testable logic separate from transport."""

from __future__ import annotations

from typing import Any

from app.config import Settings, get_settings
from app.core.errors import FlightUnavailableError
from app.tools.flight_client import FlightApiClient, create_flight_api_client, normalize_travel_date


def search_flights_handler(
    *,
    origin: str,
    destination: str,
    from_date: str,
    flight_client: FlightApiClient | None = None,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    """Search scheduled flights and return serializable flight options."""
    client = flight_client or create_flight_api_client(settings or get_settings())
    api_date = normalize_travel_date(from_date)
    try:
        options = client.search_schedules(
            origin=origin.strip().upper(),
            destination=destination.strip().upper(),
            from_date=api_date,
            direct_flights=True,
        )
    except FlightApiError as exc:
        raise FlightUnavailableError(
            user_message=(
                "I couldn't retrieve live flight schedules right now. Please try again later."
            ),
        ) from exc
    return [option.model_dump() for option in options]


def get_flight_status_handler(
    *,
    flight_number: str,
    date: str,
    flight_client: FlightApiClient | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Fetch operational status for one flight number."""
    client = flight_client or create_flight_api_client(settings or get_settings())
    api_date = normalize_travel_date(date)
    normalized_number = flight_number.replace(" ", "").upper()
    try:
        status = client.get_flight_status(
            flight_number=normalized_number,
            date=api_date,
        )
    except FlightApiError as exc:
        raise FlightUnavailableError(
            user_message=(
                "I couldn't retrieve live flight status right now. Please try again later."
            ),
        ) from exc

    if status is None:
        return {
            "found": False,
            "flight_number": normalized_number,
            "date": api_date,
        }
    return {"found": True, **status.model_dump()}
