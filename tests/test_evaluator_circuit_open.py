"""Evaluator circuit-open tests — Phase 9.6."""

import httpx
import pytest

from app.agent.loop import run_chat
from app.agent.state import InMemoryStateStore
from app.config import Settings
from app.core.circuit_breaker import CircuitBreakerPolicy, get_circuit_breaker
from app.models.agent import EvaluationStatus
from app.models.planning import PlanStatus
from app.tools.adapters.direct import DirectToolAdapter
from app.tools.booking_service import BookingService
from app.tools.flight_service import FlightSearchService
from app.tools.lufthansa_client import LufthansaClient, LufthansaFlightApiClient


def _open_lufthansa_circuit() -> None:
    breaker = get_circuit_breaker()
    policy = CircuitBreakerPolicy(
        enabled=True,
        failure_threshold=1,
        window_seconds=60.0,
        open_seconds=30.0,
    )
    breaker.record_failure("lufthansa_api", policy)


def test_run_chat_returns_understandable_message_when_circuit_open(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _open_lufthansa_circuit()

    settings = Settings(
        flight_api_use_mock=False,
        flight_api_key="id",
        flight_api_client_secret="secret",
        retry_enabled=False,
        circuit_breaker_enabled=True,
        circuit_breaker_failure_threshold=1,
        booking_db_path=str(tmp_path / "bookings.db"),
    )
    http_client = httpx.Client(
        base_url="https://api.lufthansa.com/v1",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"access_token": "test-token", "expires_in": 3600},
            )
            if request.url.path.endswith("/oauth/token")
            else httpx.Response(503, json={"error": "unavailable"}),
        ),
    )
    adapter = DirectToolAdapter(
        settings=settings,
        flight_service=FlightSearchService(
            settings=settings,
            flight_client=LufthansaFlightApiClient(
                settings=settings,
                lufthansa_client=LufthansaClient(settings=settings, http_client=http_client),
            ),
        ),
        booking_service=BookingService(settings=settings),
    )
    monkeypatch.setattr(
        "app.tools.adapters.create_tool_adapter",
        lambda settings=None: adapter,
    )

    store = InMemoryStateStore()
    state, message = run_chat(
        user_message="Find flights TIA to FRA on 2025-09-15",
        trace_id="trace-circuit",
        conversation_id="conv-circuit",
        settings=settings,
        store=store,
    )

    assert state.plan.status == PlanStatus.FAILED
    assert state.reflection_history[-1].status == EvaluationStatus.FAIL
    assert "temporarily unavailable" in message
    assert "circuit breaker" not in message.lower()
