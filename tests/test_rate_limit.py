"""Rate limiting tests — Phase 8.3."""

from fastapi.testclient import TestClient

from app.config import Settings
from app.guardrails.rate_limit import check_conversation_rate_limit, check_ip_rate_limit
from app.main import create_app


def test_check_ip_rate_limit_blocks_after_threshold() -> None:
    settings = Settings(rate_limit_enabled=True, rate_limit_ip_requests=2, rate_limit_window_seconds=60)

    first = check_ip_rate_limit("127.0.0.1", settings=settings)
    second = check_ip_rate_limit("127.0.0.1", settings=settings)
    third = check_ip_rate_limit("127.0.0.1", settings=settings)

    assert first.allowed is True
    assert second.allowed is True
    assert third.allowed is False
    assert third.retry_after_seconds is not None


def test_check_conversation_rate_limit_blocks_after_threshold() -> None:
    settings = Settings(
        rate_limit_enabled=True,
        rate_limit_conversation_requests=2,
        rate_limit_window_seconds=60,
    )

    first = check_conversation_rate_limit("conv1", settings=settings)
    second = check_conversation_rate_limit("conv1", settings=settings)
    third = check_conversation_rate_limit("conv1", settings=settings)

    assert first.allowed is True
    assert second.allowed is True
    assert third.allowed is False


def test_chat_returns_429_when_ip_limit_exceeded() -> None:
    settings = Settings(
        rate_limit_enabled=True,
        rate_limit_ip_requests=2,
        rate_limit_window_seconds=60,
        flight_api_use_mock=True,
    )
    client = TestClient(create_app(settings=settings))
    payload = {"message": "Find flights TIA to FRA on 2025-09-15"}

    assert client.post("/chat", json=payload).status_code == 200
    assert client.post("/chat", json=payload).status_code == 200
    response = client.post("/chat", json=payload)

    assert response.status_code == 429
    assert response.json()["detail"] == "Too many requests. Please try again later."
    assert "Retry-After" in response.headers


def test_chat_returns_429_when_conversation_limit_exceeded() -> None:
    settings = Settings(
        rate_limit_enabled=True,
        rate_limit_ip_requests=100,
        rate_limit_conversation_requests=2,
        rate_limit_window_seconds=60,
        flight_api_use_mock=True,
    )
    client = TestClient(create_app(settings=settings))
    conversation_id = "conv-rate-limit"
    payload = {
        "message": "Find flights TIA to FRA on 2025-09-15",
        "conversation_id": conversation_id,
    }

    assert client.post("/chat", json=payload).status_code == 200
    assert client.post("/chat", json=payload).status_code == 200
    response = client.post("/chat", json=payload)

    assert response.status_code == 429
    assert "conversation" in response.json()["detail"].lower()


def test_health_is_not_rate_limited() -> None:
    settings = Settings(rate_limit_enabled=True, rate_limit_ip_requests=1, rate_limit_window_seconds=60)
    client = TestClient(create_app(settings=settings))

    assert client.get("/health").status_code == 200
    assert client.get("/health").status_code == 200
