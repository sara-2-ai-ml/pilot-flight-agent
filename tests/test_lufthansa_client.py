"""Lufthansa HTTP client tests — Phase 5.1."""

import httpx
import pytest

from app.config import Settings
from app.tools.lufthansa_client import (
    LufthansaApiError,
    LufthansaClient,
    LufthansaFlightApiClient,
    create_lufthansa_client,
)

SAMPLE_SCHEDULE_RESPONSE = {
    "ScheduleResource": {
        "Schedule": [
            {
                "Flight": {
                    "MarketingCarrier": {"FlightNumber": "400"},
                    "Departure": {"AirportCode": "TIA", "ScheduledTimeLocal": "2025-09-15T06:30"},
                    "Arrival": {"AirportCode": "FRA", "ScheduledTimeLocal": "2025-09-15T08:45"},
                }
            }
        ]
    }
}


def _build_mock_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/oauth/token"):
            return httpx.Response(
                200,
                json={"access_token": "test-token", "expires_in": 3600},
            )
        if path.endswith("/operations/schedules/TIA/FRA/2025-09-15"):
            assert request.headers["Authorization"] == "Bearer test-token"
            assert request.headers["Accept"] == "application/json"
            return httpx.Response(200, json=SAMPLE_SCHEDULE_RESPONSE)
        if path.endswith("/operations/flightstatus/LH400/2025-09-15"):
            return httpx.Response(
                200,
                json={"FlightStatusResource": {"Flights": {"Flight": {"FlightNumber": "LH400"}}}},
            )
        return httpx.Response(404, json={"error": "not found"})

    return httpx.MockTransport(handler)


def test_create_lufthansa_client_uses_injected_http_client() -> None:
    transport = _build_mock_transport()
    http_client = httpx.Client(
        base_url="https://api.lufthansa.com/v1",
        transport=transport,
    )
    settings = Settings(
        flight_api_key="client-id",
        flight_api_client_secret="client-secret",
    )

    client = create_lufthansa_client(settings=settings, http_client=http_client)

    assert isinstance(client, LufthansaClient)


def test_fetch_access_token_posts_client_credentials() -> None:
    transport = _build_mock_transport()
    http_client = httpx.Client(
        base_url="https://api.lufthansa.com/v1",
        transport=transport,
    )
    settings = Settings(
        flight_api_key="client-id",
        flight_api_client_secret="client-secret",
    )
    client = LufthansaClient(settings=settings, http_client=http_client)

    token = client.fetch_access_token()

    assert token.access_token == "test-token"
    assert token.expires_in == 3600


def test_get_schedules_returns_mocked_json_payload() -> None:
    transport = _build_mock_transport()
    http_client = httpx.Client(
        base_url="https://api.lufthansa.com/v1",
        transport=transport,
    )
    settings = Settings(
        flight_api_key="client-id",
        flight_api_client_secret="client-secret",
    )
    client = LufthansaClient(settings=settings, http_client=http_client)

    payload = client.get_schedules(
        origin="tia",
        destination="fra",
        from_date="2025-09-15",
        direct_flights=True,
    )

    assert "ScheduleResource" in payload
    assert payload["ScheduleResource"]["Schedule"][0]["Flight"]["MarketingCarrier"]["FlightNumber"] == "400"


def test_get_flight_status_returns_mocked_json_payload() -> None:
    transport = _build_mock_transport()
    http_client = httpx.Client(
        base_url="https://api.lufthansa.com/v1",
        transport=transport,
    )
    settings = Settings(
        flight_api_key="client-id",
        flight_api_client_secret="client-secret",
    )
    client = LufthansaClient(settings=settings, http_client=http_client)

    payload = client.get_flight_status(flight_number="lh400", date="2025-09-15")

    assert payload["FlightStatusResource"]["Flights"]["Flight"]["FlightNumber"] == "LH400"


def test_fetch_access_token_requires_credentials() -> None:
    client = LufthansaClient(
        settings=Settings(flight_api_key=None, flight_api_client_secret=None),
        http_client=httpx.Client(base_url="https://api.lufthansa.com/v1"),
    )

    with pytest.raises(LufthansaApiError, match="credentials are not configured"):
        client.fetch_access_token()


def test_get_schedules_raises_on_api_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth/token"):
            return httpx.Response(200, json={"access_token": "test-token", "expires_in": 3600})
        return httpx.Response(503, json={"error": "unavailable"})

    http_client = httpx.Client(
        base_url="https://api.lufthansa.com/v1",
        transport=httpx.MockTransport(handler),
    )
    client = LufthansaClient(
        settings=Settings(
            flight_api_key="id",
            flight_api_client_secret="secret",
            retry_base_delay_seconds=0.01,
            retry_max_delay_seconds=0.01,
        ),
        http_client=http_client,
    )

    with pytest.raises(LufthansaApiError, match="request failed"):
        client.get_schedules(origin="TIA", destination="FRA", from_date="2025-09-15")


def test_get_schedules_retries_flaky_api_then_succeeds() -> None:
    schedule_attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth/token"):
            return httpx.Response(200, json={"access_token": "test-token", "expires_in": 3600})
        if request.url.path.endswith("/operations/schedules/TIA/FRA/2025-09-15"):
            schedule_attempts["count"] += 1
            if schedule_attempts["count"] < 3:
                return httpx.Response(503, json={"error": "temporary"})
            return httpx.Response(200, json=SAMPLE_SCHEDULE_RESPONSE)
        return httpx.Response(404, json={"error": "not found"})

    client = LufthansaClient(
        settings=Settings(
            flight_api_key="id",
            flight_api_client_secret="secret",
            retry_base_delay_seconds=0.01,
            retry_max_delay_seconds=0.01,
        ),
        http_client=httpx.Client(
            base_url="https://api.lufthansa.com/v1",
            transport=httpx.MockTransport(handler),
        ),
    )

    payload = client.get_schedules(origin="TIA", destination="FRA", from_date="2025-09-15")

    assert schedule_attempts["count"] == 3
    assert payload["ScheduleResource"]["Schedule"][0]["Flight"]["MarketingCarrier"]["FlightNumber"] == "400"


def test_get_schedules_fails_after_three_flaky_attempts() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth/token"):
            return httpx.Response(200, json={"access_token": "test-token", "expires_in": 3600})
        return httpx.Response(503, json={"error": "temporary"})

    client = LufthansaClient(
        settings=Settings(
            flight_api_key="id",
            flight_api_client_secret="secret",
            retry_base_delay_seconds=0.01,
            retry_max_delay_seconds=0.01,
        ),
        http_client=httpx.Client(
            base_url="https://api.lufthansa.com/v1",
            transport=httpx.MockTransport(handler),
        ),
    )

    with pytest.raises(LufthansaApiError, match="request failed"):
        client.get_schedules(origin="TIA", destination="FRA", from_date="2025-09-15")


def test_lufthansa_flight_api_client_returns_domain_models() -> None:
    transport = _build_mock_transport()
    http_client = httpx.Client(
        base_url="https://api.lufthansa.com/v1",
        transport=transport,
    )
    settings = Settings(
        flight_api_key="client-id",
        flight_api_client_secret="client-secret",
    )
    client = LufthansaFlightApiClient(settings=settings, http_client=http_client)

    options = client.search_schedules(
        origin="TIA",
        destination="FRA",
        from_date="2025-09-15",
    )
    status = client.get_flight_status(flight_number="LH400", date="2025-09-15")

    assert len(options) == 1
    assert options[0].id == "LH400"
    assert status is not None
    assert status.flight_number == "LH400"
