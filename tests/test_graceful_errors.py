"""Graceful worker error tests — Phase 9.5."""

from unittest.mock import MagicMock

import pytest

from app.agent.state import AgentState
from app.agent.workers.flight_worker import FlightWorker
from app.config import Settings
from app.core.circuit_breaker import CircuitBreakerOpenError
from app.core.errors import (
    ErrorCode,
    FlightUnavailableError,
    graceful_error_from_exception,
    to_worker_failure,
)
from app.mcp.result_parsing import McpClientError
from app.tools.adapters.base import ToolAdapter
from app.tools.flight_client import FlightApiError
from app.tools.flight_service import FlightSearchService


def test_graceful_error_from_exception_maps_flight_api_error() -> None:
    error = graceful_error_from_exception(FlightApiError("secret upstream detail"))

    assert isinstance(error, FlightUnavailableError)
    assert error.code == ErrorCode.FLIGHT_UNAVAILABLE.value
    assert "secret upstream detail" not in error.user_message


def test_graceful_error_from_exception_maps_circuit_open() -> None:
    from app.core.errors import GracefulError

    error = graceful_error_from_exception(
        CircuitBreakerOpenError("Circuit 'lufthansa_api' is open; failing fast.", circuit="x"),
    )

    assert isinstance(error, GracefulError)
    assert error.code == ErrorCode.CIRCUIT_OPEN.value
    assert error.retryable is False
    assert "temporarily unavailable" in error.user_message


def test_to_worker_failure_returns_safe_worker_result() -> None:
    result = to_worker_failure(
        FlightUnavailableError(
            user_message="Flight data is unavailable right now.",
        ),
    )

    assert result.success is False
    assert result.message == "Flight data is unavailable right now."
    assert result.error_code == ErrorCode.FLIGHT_UNAVAILABLE.value
    assert result.retryable is True


def test_flight_service_raises_graceful_error_on_api_failure() -> None:
    mock_client = MagicMock()
    mock_client.search_schedules.side_effect = FlightApiError("request failed")
    service = FlightSearchService(
        settings=Settings(flight_api_use_mock=False),
        flight_client=mock_client,
    )
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.user_message = "Find flights TIA to FRA on 2025-09-15"

    with pytest.raises(FlightUnavailableError, match="couldn't retrieve live flight schedules"):
        service.search_flights(state)


class _ExplodingAdapter(ToolAdapter):
    @property
    def mode(self):
        from app.config import ToolsMode

        return ToolsMode.DIRECT

    def search_flights(self, state: AgentState):
        raise RuntimeError("secret database password leaked")

    def validate_options(self, state: AgentState):
        raise RuntimeError("should not run")

    def create_booking(self, state: AgentState):
        raise RuntimeError("should not run")


def test_worker_execute_converts_raw_exception_to_graceful_result() -> None:
    worker = FlightWorker(adapter=_ExplodingAdapter())
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.user_message = "Find flights TIA to FRA on 2025-09-15"

    result = worker.execute("search_flights", state)

    assert result.success is False
    assert result.error_code == ErrorCode.UNEXPECTED.value
    assert "password" not in result.message
    assert result.message.startswith("Something went wrong")


def test_worker_execute_preserves_graceful_error_message() -> None:
    class _GracefulAdapter(ToolAdapter):
        @property
        def mode(self):
            from app.config import ToolsMode

            return ToolsMode.DIRECT

        def search_flights(self, state: AgentState):
            raise FlightUnavailableError(
                user_message="Flights are temporarily unavailable.",
            )

        def validate_options(self, state: AgentState):
            raise FlightUnavailableError(user_message="unused")

        def create_booking(self, state: AgentState):
            raise FlightUnavailableError(user_message="unused")

    worker = FlightWorker(adapter=_GracefulAdapter())
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.user_message = "Find flights TIA to FRA"

    result = worker.execute("search_flights", state)

    assert result.success is False
    assert result.message == "Flights are temporarily unavailable."
    assert result.error_code == ErrorCode.FLIGHT_UNAVAILABLE.value


def test_graceful_error_from_exception_maps_mcp_client_error() -> None:
    error = graceful_error_from_exception(
        McpClientError("internal MCP transport exploded"),
    )

    assert error.code == ErrorCode.MCP_UNAVAILABLE.value
    assert "exploded" not in error.user_message
