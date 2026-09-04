"""Structured logging tests."""

import io
import json
import logging

from fastapi.testclient import TestClient

from app.core.logging import StructuredFormatter, setup_logging
from app.main import app


def test_setup_logging_is_idempotent() -> None:
    setup_logging("INFO")
    setup_logging("DEBUG")
    assert logging.getLogger("app").level == logging.DEBUG


def test_structured_formatter_includes_trace_id() -> None:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(StructuredFormatter())

    test_logger = logging.getLogger("app.test.formatter")
    test_logger.handlers = [handler]
    test_logger.propagate = False
    test_logger.setLevel(logging.INFO)

    test_logger.info("hello", extra={"trace_id": "abc123", "event": "unit_test"})

    line = json.loads(stream.getvalue().strip())
    assert line["trace_id"] == "abc123"
    assert line["event"] == "unit_test"
    assert line["message"] == "hello"


def test_health_includes_trace_header() -> None:
    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 200
    assert len(response.headers["X-Trace-Id"]) == 32


def test_chat_trace_id_matches_header() -> None:
    client = TestClient(app)
    response = client.post("/chat", json={"message": "Hello Pilot"})

    body = response.json()
    assert body["trace_id"] == response.headers["X-Trace-Id"]
