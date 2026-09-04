"""Flight API client tests — Phase 5.6."""

from app.config import Settings
from app.tools.flight_client import MockFlightApiClient, create_flight_api_client


def test_create_flight_api_client_returns_mock_by_default() -> None:
    client = create_flight_api_client(Settings(flight_api_use_mock=True))

    assert isinstance(client, MockFlightApiClient)


def test_mock_flight_api_client_returns_domain_models() -> None:
    client = MockFlightApiClient()

    options = client.search_schedules(
        origin="TIA",
        destination="FRA",
        from_date="2025-09-15",
    )
    status = client.get_flight_status(flight_number="LH400", date="2025-09-15")

    assert len(options) == 3
    assert options[0].origin == "TIA"
    assert status is not None
    assert status.flight_number == "LH400"
