"""Output guard tests — Phase 8.4."""

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import Settings
from app.guardrails.output_guard import (
    SAFE_OUTPUT_FALLBACK,
    filter_user_response,
)
from app.main import app


def test_filter_user_response_allows_normal_flight_message() -> None:
    message = "Found 3 mock flights from TIA to FRA on 2025-09-15."

    result = filter_user_response(message, settings=Settings())

    assert result.message == message
    assert result.sanitized is False
    assert result.blocked is False


def test_filter_user_response_blocks_traceback_output() -> None:
    message = (
        "Something failed.\nTraceback (most recent call last):\n"
        "  File \"app/agent/loop.py\", line 10, in run_chat\n"
        "    raise RuntimeError('boom')"
    )

    result = filter_user_response(message, settings=Settings())

    assert result.message == SAFE_OUTPUT_FALLBACK
    assert result.blocked is True
    assert "traceback" in result.reasons


def test_filter_user_response_redacts_api_keys() -> None:
    message = "Use key sk-abcdefghijklmnopqrstuvwxyz123456 to continue."

    result = filter_user_response(message, settings=Settings())

    assert "[REDACTED_SECRET]" in result.message
    assert "sk-abc" not in result.message
    assert result.sanitized is True
    assert result.blocked is False


def test_filter_user_response_redacts_internal_paths() -> None:
    message = "Failed reading C:\\Users\\User\\app\\agent\\loop.py during search."

    result = filter_user_response(message, settings=Settings())

    assert "[REDACTED_PATH]" in result.message
    assert "loop.py" not in result.message


def test_filter_user_response_can_be_disabled() -> None:
    message = "Traceback (most recent call last): boom"

    result = filter_user_response(message, settings=Settings(output_guard_enabled=False))

    assert result.message == message
    assert result.sanitized is False


def test_chat_filters_unsafe_agent_message() -> None:
    client = TestClient(app)

    with patch(
        "app.api.chat.run_chat",
        return_value=(
            type("State", (), {"conversation_id": "conv1", "pending_approval": None, "iteration_count": 1})(),
            "Traceback (most recent call last):\n  File \"app/agent/loop.py\"",
        ),
    ):
        response = client.post("/chat", json={"message": "Find flights TIA to FRA"})

    assert response.status_code == 200
    assert response.json()["message"] == SAFE_OUTPUT_FALLBACK
    assert "Traceback" not in response.json()["message"]
