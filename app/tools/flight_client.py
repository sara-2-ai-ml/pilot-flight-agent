"""Flight API client interface — workers depend on this, not a specific provider."""

from __future__ import annotations

from datetime import date
from typing import Protocol

from app.config import FlightApiProvider, Settings, get_settings
from app.models.flight import FlightOption, FlightStatusInfo


class FlightApiError(Exception):
    """Raised when a flight data provider cannot fulfill a request."""

    def __init__(self, message: str, *, code: str | None = None) -> None:
        self.code = code
        super().__init__(message)


def normalize_travel_date(travel_date: str | None) -> str:
    """Return an API-compatible YYYY-MM-DD date."""
    if travel_date and len(travel_date) == 10 and travel_date[4] == "-" and travel_date[7] == "-":
        return travel_date
    return date.today().isoformat()


def mock_flight_status(*, flight_number: str, travel_date: str) -> FlightStatusInfo:
    """Deterministic mock status for local development and tests."""
    return FlightStatusInfo(
        flight_number=flight_number.upper(),
        date=travel_date,
        origin="FRA",
        destination="JFK",
        scheduled_departure=f"{travel_date}T10:00",
        scheduled_arrival=f"{travel_date}T13:30",
        status="On Time",
    )


def mock_flight_options(
    *,
    origin: str,
    destination: str,
    travel_date: str | None,
) -> list[FlightOption]:
    """Deterministic mock results for local development and tests."""
    date_label = normalize_travel_date(travel_date)
    return [
        FlightOption(
            id="LH001",
            origin=origin,
            destination=destination,
            departure_time=f"{date_label}T06:30",
            arrival_time=f"{date_label}T08:45",
        ),
        FlightOption(
            id="LH002",
            origin=origin,
            destination=destination,
            departure_time=f"{date_label}T12:15",
            arrival_time=f"{date_label}T14:30",
        ),
        FlightOption(
            id="LH003",
            origin=origin,
            destination=destination,
            departure_time=f"{date_label}T18:00",
            arrival_time=f"{date_label}T20:10",
        ),
    ]


class FlightApiClient(Protocol):
    """Provider-agnostic flight data access used by workers and services."""

    def search_schedules(
        self,
        *,
        origin: str,
        destination: str,
        from_date: str,
        direct_flights: bool = True,
    ) -> list[FlightOption]:
        """Return normalized flight options for a route and date."""

    def get_flight_status(
        self,
        *,
        flight_number: str,
        date: str,
    ) -> FlightStatusInfo | None:
        """Return normalized operational status for one flight number."""


class MockFlightApiClient:
    """In-memory flight provider for tests and local development."""

    def search_schedules(
        self,
        *,
        origin: str,
        destination: str,
        from_date: str,
        direct_flights: bool = True,
    ) -> list[FlightOption]:
        return mock_flight_options(
            origin=origin.upper(),
            destination=destination.upper(),
            travel_date=from_date,
        )

    def get_flight_status(
        self,
        *,
        flight_number: str,
        date: str,
    ) -> FlightStatusInfo | None:
        return mock_flight_status(
            flight_number=flight_number.replace(" ", "").upper(),
            travel_date=date,
        )


def create_flight_api_client(
    settings: Settings | None = None,
    *,
    flight_client: FlightApiClient | None = None,
) -> FlightApiClient:
    """Build the configured flight provider implementation."""
    if flight_client is not None:
        return flight_client

    resolved = settings or get_settings()
    if resolved.flight_api_use_mock:
        return MockFlightApiClient()

    if resolved.flight_api_provider == FlightApiProvider.AVIATIONSTACK:
        from app.tools.aviationstack_client import AviationStackFlightApiClient

        return AviationStackFlightApiClient(settings=resolved)

    from app.tools.lufthansa_client import LufthansaFlightApiClient

    return LufthansaFlightApiClient(settings=resolved)
