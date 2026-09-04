"""AviationStack HTTP client tests."""

import httpx
import pytest

from app.config import FlightApiProvider, Settings
from app.tools.aviationstack_client import (
    AviationStackApiError,
    AviationStackClient,
    AviationStackFlightApiClient,
    create_aviationstack_client,
)
from app.tools.flight_client import create_flight_api_client
from app.tools.lufthansa_client import LufthansaFlightApiClient

SAMPLE_AVIATIONSTACK_FLIGHTS_RESPONSE = {
    "pagination": {"limit": 100, "offset": 0, "count": 1, "total": 1},
    "data": [
        {
            "flight_date": "2025-09-15",
            "flight_status": "scheduled",
            "departure": {
                "iata": "TIA",
                "scheduled": "2025-09-15T06:30:00+00:00",
            },
            "arrival": {
                "iata": "FRA",
                "scheduled": "2025-09-15T08:45:00+00:00",
            },
            "airline": {"iata": "LH", "name": "Lufthansa"},
            "flight": {"iata": "LH400", "number": "400"},
        }
    ],
}


def _build_mock_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if not request.url.path.endswith("/flights"):
            return httpx.Response(404, json={"error": {"message": "not found"}})

        params = dict(request.url.params)
        assert params["access_key"] == "test-access-key"

        if (
            params.get("dep_iata") == "TIA"
            and params.get("arr_iata") == "FRA"
            and params.get("flight_date") == "2025-09-15"
        ):
            return httpx.Response(200, json=SAMPLE_AVIATIONSTACK_FLIGHTS_RESPONSE)

        if params.get("flight_iata") == "LH400" and params.get("flight_date") == "2025-09-15":
            return httpx.Response(200, json=SAMPLE_AVIATIONSTACK_FLIGHTS_RESPONSE)

        return httpx.Response(200, json={"pagination": {}, "data": []})

    return httpx.MockTransport(handler)


def test_create_aviationstack_client_uses_injected_http_client() -> None:
    http_client = httpx.Client(
        base_url="https://api.aviationstack.com/v1",
        transport=_build_mock_transport(),
    )
    settings = Settings(
        flight_api_key="test-access-key",
        flight_api_base_url="https://api.aviationstack.com/v1",
    )

    client = create_aviationstack_client(settings=settings, http_client=http_client)

    assert isinstance(client, AviationStackClient)


def test_get_flights_passes_access_key_and_route_params() -> None:
    http_client = httpx.Client(
        base_url="https://api.aviationstack.com/v1",
        transport=_build_mock_transport(),
    )
    client = AviationStackClient(
        settings=Settings(flight_api_key="test-access-key"),
        http_client=http_client,
    )

    payload = client.get_flights(
        dep_iata="tia",
        arr_iata="fra",
        flight_date="2025-09-15",
    )

    assert len(payload["data"]) == 1
    assert payload["data"][0]["flight"]["iata"] == "LH400"


def test_get_flights_requires_access_key() -> None:
    client = AviationStackClient(
        settings=Settings(flight_api_key=None),
        http_client=httpx.Client(base_url="https://api.aviationstack.com/v1"),
    )

    with pytest.raises(AviationStackApiError, match="access key is not configured"):
        client.get_flights(dep_iata="TIA", arr_iata="FRA", flight_date="2025-09-15")


def test_aviationstack_flight_api_client_returns_domain_models() -> None:
    http_client = httpx.Client(
        base_url="https://api.aviationstack.com/v1",
        transport=_build_mock_transport(),
    )
    client = AviationStackFlightApiClient(
        settings=Settings(flight_api_key="test-access-key"),
        http_client=http_client,
    )

    options = client.search_schedules(
        origin="TIA",
        destination="FRA",
        from_date="2025-09-15",
    )
    status = client.get_flight_status(flight_number="LH400", date="2025-09-15")

    assert len(options) == 1
    assert options[0].id == "LH400"
    assert options[0].origin == "TIA"
    assert status is not None
    assert status.flight_number == "LH400"
    assert status.status == "Scheduled"


def test_create_flight_api_client_selects_aviationstack_provider() -> None:
    client = create_flight_api_client(
        Settings(
            flight_api_use_mock=False,
            flight_api_provider=FlightApiProvider.AVIATIONSTACK,
            flight_api_key="test-access-key",
            flight_api_base_url="https://api.aviationstack.com/v1",
        ),
    )

    assert isinstance(client, AviationStackFlightApiClient)


def test_create_flight_api_client_keeps_lufthansa_default() -> None:
    client = create_flight_api_client(
        Settings(
            flight_api_use_mock=False,
            flight_api_provider=FlightApiProvider.LUFTHANSA,
            flight_api_key="client-id",
            flight_api_client_secret="client-secret",
        ),
    )

    assert isinstance(client, LufthansaFlightApiClient)
