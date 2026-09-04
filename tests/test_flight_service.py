"""Flight service tests — Phase 4.3 / 5.6."""

from unittest.mock import MagicMock

import pytest

from app.agent.state import AgentState
from app.config import Settings
from app.models.flight import normalize_flight_status_payload, normalize_schedule_payload
from app.core.errors import FlightUnavailableError
from app.tools.flight_client import FlightApiError, mock_flight_options, normalize_travel_date
from app.tools.flight_service import (
    FlightSearchService,
    parse_flight_number,
    parse_route,
    parse_travel_date,
)
from tests.test_flight_normalizer import SAMPLE_SCHEDULE_PAYLOAD, SAMPLE_STATUS_PAYLOAD


def test_parse_route_extracts_iata_codes() -> None:
    assert parse_route("Find flights TIA to FRA") == ("TIA", "FRA")
    assert parse_route("from tia-fra tomorrow") == ("TIA", "FRA")


def test_parse_travel_date_extracts_iso_date() -> None:
    assert parse_travel_date("Find flights TIA to FRA on 2025-09-15") == "2025-09-15"


def test_search_flights_populates_state_with_mock_results() -> None:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.user_message = "Find flights TIA to FRA on 2025-09-15"
    service = FlightSearchService(settings=Settings(flight_api_use_mock=True))

    result = service.search_flights(state)

    assert result.success is True
    assert "Found 3 mock flights from TIA to FRA" in result.message
    assert state.flight_search.origin == "TIA"
    assert state.flight_search.destination == "FRA"
    assert state.flight_search.date == "2025-09-15"
    assert len(state.flight_search.results) == 3
    assert state.flight_search.results[0].id == "LH001"


def test_search_flights_fails_without_route() -> None:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.user_message = "Find flights tomorrow"
    service = FlightSearchService(settings=Settings(flight_api_use_mock=True))

    result = service.search_flights(state)

    assert result.success is False
    assert result.error_code == "missing_route"
    assert state.flight_search.results == []


def test_validate_options_selects_first_result() -> None:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.user_message = "Find flights TIA to FRA"
    state.flight_search.results = mock_flight_options(
        origin="TIA",
        destination="FRA",
        travel_date="2025-09-15",
    )
    service = FlightSearchService()

    result = service.validate_options(state)

    assert result.success is True
    assert state.flight_search.selected_option_id == "LH001"
    assert "Selected flight LH001" in result.message


def test_validate_options_fails_without_results() -> None:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    service = FlightSearchService()

    result = service.validate_options(state)

    assert result.success is False


def test_parse_flight_number_extracts_carrier_and_number() -> None:
    assert parse_flight_number("Status for flight LH400 tomorrow") == "LH400"
    assert parse_flight_number("What about LH 400?") == "LH400"
    assert parse_flight_number("Find flights TIA to FRA on 2025-09-15") is None


def test_get_flight_status_returns_mock_status() -> None:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    service = FlightSearchService(settings=Settings(flight_api_use_mock=True))

    result = service.get_flight_status(
        flight_number="LH400",
        travel_date="2025-09-15",
        state=state,
    )

    assert result.success is True
    assert "Mock status for LH400" in result.message
    assert state.flight_search.last_status is not None
    assert state.flight_search.last_status.status == "On Time"


def test_get_flight_status_uses_live_client_when_mock_disabled() -> None:
    mock_client = MagicMock()
    mock_client.get_flight_status.return_value = normalize_flight_status_payload(
        SAMPLE_STATUS_PAYLOAD
    )
    service = FlightSearchService(
        settings=Settings(flight_api_use_mock=False),
        flight_client=mock_client,
    )

    result = service.get_flight_status(flight_number="lh400", travel_date="2025-09-15")

    assert result.success is True
    assert "Live status for LH400 on 2025-09-15: On Time." in result.message
    mock_client.get_flight_status.assert_called_once_with(
        flight_number="LH400",
        date="2025-09-15",
    )


def test_get_flight_status_live_handles_api_errors() -> None:
    mock_client = MagicMock()
    mock_client.get_flight_status.side_effect = FlightApiError("request failed")
    service = FlightSearchService(
        settings=Settings(flight_api_use_mock=False),
        flight_client=mock_client,
    )

    with pytest.raises(FlightUnavailableError, match="couldn't retrieve live flight status"):
        service.get_flight_status(flight_number="LH400", travel_date="2025-09-15")


def test_get_flight_status_live_fails_when_status_missing() -> None:
    mock_client = MagicMock()
    mock_client.get_flight_status.return_value = None
    service = FlightSearchService(
        settings=Settings(flight_api_use_mock=False),
        flight_client=mock_client,
    )

    result = service.get_flight_status(flight_number="LH400", travel_date="2025-09-15")

    assert result.success is False
    assert "No status found for flight LH400" in result.message


def test_normalize_travel_date_defaults_to_iso_today() -> None:
    iso_today = normalize_travel_date(None)
    assert len(iso_today) == 10
    assert iso_today[4] == "-"


def test_search_flights_uses_live_client_when_mock_disabled() -> None:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.user_message = "Find flights TIA to FRA on 2025-09-15"
    mock_client = MagicMock()
    mock_client.search_schedules.return_value = normalize_schedule_payload(SAMPLE_SCHEDULE_PAYLOAD)
    service = FlightSearchService(
        settings=Settings(flight_api_use_mock=False),
        flight_client=mock_client,
    )

    result = service.search_flights(state)

    assert result.success is True
    assert "Found 2 live flights from TIA to FRA" in result.message
    assert len(state.flight_search.results) == 2
    assert state.flight_search.results[0].id == "LH400"
    mock_client.search_schedules.assert_called_once_with(
        origin="TIA",
        destination="FRA",
        from_date="2025-09-15",
        direct_flights=True,
    )


def test_search_flights_live_handles_api_errors() -> None:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.user_message = "Find flights TIA to FRA on 2025-09-15"
    mock_client = MagicMock()
    mock_client.search_schedules.side_effect = FlightApiError("request failed")
    service = FlightSearchService(
        settings=Settings(flight_api_use_mock=False),
        flight_client=mock_client,
    )

    with pytest.raises(FlightUnavailableError, match="couldn't retrieve live flight schedules"):
        service.search_flights(state)


def test_search_flights_live_fails_when_no_flights_found() -> None:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.user_message = "Find flights TIA to FRA on 2025-09-15"
    mock_client = MagicMock()
    mock_client.search_schedules.return_value = []
    service = FlightSearchService(
        settings=Settings(flight_api_use_mock=False),
        flight_client=mock_client,
    )

    result = service.search_flights(state)

    assert result.success is False
    assert "No flights found" in result.message
