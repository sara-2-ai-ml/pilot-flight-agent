"""PII redaction tests — Phase 8.5."""

import io
import json
import logging
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import Settings
from app.core.logging import StructuredFormatter
from app.guardrails.pii import REDACTED_EMAIL, REDACTED_PHONE, redact_pii
from app.main import app


def test_redact_pii_masks_email() -> None:
    result = redact_pii(
        "Contact me at ana.krasniqi@example.com for updates.",
        settings=Settings(),
    )

    assert result.redacted is True
    assert "email" in result.kinds
    assert REDACTED_EMAIL in result.text
    assert "ana.krasniqi@example.com" not in result.text


def test_redact_pii_masks_phone() -> None:
    result = redact_pii(
        "Call me at +355 69 123 4567 before booking.",
        settings=Settings(),
    )

    assert result.redacted is True
    assert "phone" in result.kinds
    assert REDACTED_PHONE in result.text
    assert "+355 69 123 4567" not in result.text


def test_redact_pii_leaves_normal_flight_text_untouched() -> None:
    message = "Found 3 mock flights from TIA to FRA on 2025-09-15."

    result = redact_pii(message, settings=Settings())

    assert result.text == message
    assert result.redacted is False


def test_redact_pii_can_be_disabled() -> None:
    result = redact_pii(
        "Email ana@example.com",
        settings=Settings(pii_redaction_enabled=False),
    )

    assert result.text == "Email ana@example.com"
    assert result.redacted is False


def test_structured_formatter_redacts_pii_in_logs() -> None:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(StructuredFormatter())

    test_logger = logging.getLogger("app.test.pii")
    test_logger.handlers = [handler]
    test_logger.propagate = False
    test_logger.setLevel(logging.INFO)

    test_logger.info(
        "User said call ana@example.com or +355691234567",
        extra={"event": "unit_test"},
    )

    line = json.loads(stream.getvalue().strip())
    assert REDACTED_EMAIL in line["message"]
    assert REDACTED_PHONE in line["message"]
    assert "ana@example.com" not in line["message"]


def test_chat_redacts_pii_in_agent_response() -> None:
    client = TestClient(app)

    with patch(
        "app.api.chat.run_chat",
        return_value=(
            type(
                "State",
                (),
                {"conversation_id": "conv1", "pending_approval": None, "iteration_count": 1},
            )(),
            "Please confirm booking for ana@example.com or +355691234567.",
        ),
    ):
        response = client.post("/chat", json={"message": "Book flight TIA to FRA"})

    assert response.status_code == 200
    body = response.json()
    assert REDACTED_EMAIL in body["message"]
    assert REDACTED_PHONE in body["message"]
    assert "ana@example.com" not in body["message"]
