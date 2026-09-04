"""Circuit breaker tests — Phase 9.3."""

import httpx
import pytest

from app.config import Settings
from app.core.circuit_breaker import (
    CircuitBreakerOpenError,
    CircuitBreakerPolicy,
    get_circuit_breaker,
)
from app.tools.lufthansa_client import LufthansaApiError, LufthansaClient


def test_circuit_opens_after_failure_threshold() -> None:
    breaker = get_circuit_breaker()
    policy = CircuitBreakerPolicy(
        enabled=True,
        failure_threshold=3,
        window_seconds=60.0,
        open_seconds=30.0,
    )

    for _ in range(3):
        breaker.record_failure("test-circuit", policy)

    assert breaker.is_open("test-circuit", policy=policy) is True


def test_circuit_allow_fails_fast_when_open() -> None:
    breaker = get_circuit_breaker()
    policy = CircuitBreakerPolicy(
        enabled=True,
        failure_threshold=1,
        window_seconds=60.0,
        open_seconds=30.0,
    )
    breaker.record_failure("fast-fail", policy)

    with pytest.raises(CircuitBreakerOpenError, match="failing fast"):
        breaker.allow("fast-fail", policy)


def test_circuit_record_success_closes_open_circuit() -> None:
    breaker = get_circuit_breaker()
    policy = CircuitBreakerPolicy(
        enabled=True,
        failure_threshold=1,
        window_seconds=60.0,
        open_seconds=30.0,
    )
    breaker.record_failure("recover", policy)
    breaker.record_success("recover")

    breaker.allow("recover", policy)


def test_lufthansa_client_fails_fast_when_circuit_open() -> None:
    request_count = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        request_count["count"] += 1
        if request.url.path.endswith("/oauth/token"):
            return httpx.Response(200, json={"access_token": "test-token", "expires_in": 3600})
        return httpx.Response(503, json={"error": "unavailable"})

    settings = Settings(
        flight_api_key="id",
        flight_api_client_secret="secret",
        retry_enabled=False,
        circuit_breaker_enabled=True,
        circuit_breaker_failure_threshold=5,
        circuit_breaker_window_seconds=60.0,
        circuit_breaker_open_seconds=30.0,
    )
    client = LufthansaClient(
        settings=settings,
        http_client=httpx.Client(
            base_url="https://api.lufthansa.com/v1",
            transport=httpx.MockTransport(handler),
        ),
    )

    for _ in range(5):
        with pytest.raises(LufthansaApiError, match="request failed"):
            client.get_schedules(origin="TIA", destination="FRA", from_date="2025-09-15")

    calls_before_open = request_count["count"]

    with pytest.raises(LufthansaApiError, match="circuit breaker is open"):
        client.get_schedules(origin="TIA", destination="FRA", from_date="2025-09-15")

    assert request_count["count"] == calls_before_open


def test_lufthansa_client_does_not_trip_circuit_on_client_errors() -> None:
    breaker = get_circuit_breaker()
    policy = CircuitBreakerPolicy(
        enabled=True,
        failure_threshold=2,
        window_seconds=60.0,
        open_seconds=30.0,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth/token"):
            return httpx.Response(200, json={"access_token": "test-token", "expires_in": 3600})
        return httpx.Response(404, json={"error": "not found"})

    client = LufthansaClient(
        settings=Settings(
            flight_api_key="id",
            flight_api_client_secret="secret",
            retry_enabled=False,
            circuit_breaker_enabled=True,
            circuit_breaker_failure_threshold=2,
        ),
        http_client=httpx.Client(
            base_url="https://api.lufthansa.com/v1",
            transport=httpx.MockTransport(handler),
        ),
    )

    for _ in range(3):
        with pytest.raises(LufthansaApiError, match="request failed"):
            client.get_schedules(origin="TIA", destination="FRA", from_date="2025-09-15")

    assert breaker.is_open("lufthansa_api", policy=policy) is False
