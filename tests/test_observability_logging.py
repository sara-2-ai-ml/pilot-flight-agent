"""Structured observability logging tests — Phase 10.1."""

import io
import json
import logging

import pytest
from fastapi.testclient import TestClient

from app.agent.coordinator import execute_step, select_current_step
from app.agent.planning import build_default_flight_plan
from app.agent.state import AgentState
from app.core.logging import StructuredFormatter, setup_logging
from app.core.observability import elapsed_ms, log_extra
from app.core.tracing import set_trace_id
from app.main import app


@pytest.fixture
def log_capture() -> io.StringIO:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(StructuredFormatter())

    app_logger = logging.getLogger("app")
    app_logger.handlers = [handler]
    app_logger.setLevel(logging.INFO)
    app_logger.propagate = False

    setup_logging("INFO")
    yield stream

    app_logger.handlers = []
    setup_logging("INFO")


def test_log_extra_includes_trace_id_from_context() -> None:
    set_trace_id("trace-obs-1")

    extra = log_extra(event="unit_test", step="search")

    assert extra["trace_id"] == "trace-obs-1"
    assert extra["event"] == "unit_test"
    assert extra["step"] == "search"


def test_structured_formatter_auto_injects_trace_id() -> None:
    set_trace_id("trace-auto-1")

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(StructuredFormatter())

    test_logger = logging.getLogger("app.test.observability")
    test_logger.handlers = [handler]
    test_logger.propagate = False
    test_logger.setLevel(logging.INFO)

    test_logger.info("hello", extra={"event": "unit_test", "step": "search", "latency_ms": 12.5})

    line = json.loads(stream.getvalue().strip())
    assert line["trace_id"] == "trace-auto-1"
    assert line["step"] == "search"
    assert line["latency_ms"] == 12.5


def test_elapsed_ms_is_non_negative() -> None:
    import time

    start = time.perf_counter()
    assert elapsed_ms(start) >= 0.0


def test_execute_step_log_contains_step_and_latency(log_capture: io.StringIO) -> None:
    set_trace_id("trace-step-1")
    state = AgentState.new(conversation_id="conv1", trace_id="trace-step-1")
    state.user_message = "Find flights TIA to FRA on Sep 15"
    state.plan = build_default_flight_plan("Find flights")
    step = select_current_step(state)

    assert step is not None
    execute_step(state, step)

    records = [json.loads(line) for line in log_capture.getvalue().strip().splitlines()]
    step_logs = [record for record in records if record.get("event") == "step_executed"]

    assert len(step_logs) == 1
    assert step_logs[0]["trace_id"] == "trace-step-1"
    assert step_logs[0]["step"] == "search"
    assert step_logs[0]["latency_ms"] >= 0.0


def test_chat_request_logs_trace_id_step_and_latency(log_capture: io.StringIO) -> None:
    client = TestClient(app)
    response = client.post("/chat", json={"message": "Find flights TIA to FRA on 2025-09-15"})

    assert response.status_code == 200
    trace_id = response.headers["X-Trace-Id"]

    records = [json.loads(line) for line in log_capture.getvalue().strip().splitlines()]
    completed = next(record for record in records if record.get("event") == "request_completed")
    step_logs = [record for record in records if record.get("event") == "step_executed"]

    assert completed["trace_id"] == trace_id
    assert completed["latency_ms"] >= 0.0
    assert step_logs
    assert step_logs[0]["trace_id"] == trace_id
    assert step_logs[0]["step"] == "search"
    assert step_logs[0]["latency_ms"] >= 0.0
