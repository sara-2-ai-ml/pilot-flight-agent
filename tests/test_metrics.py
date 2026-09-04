"""Metrics tests — Phase 10.3."""

import io
import json
import logging
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.agent.loop import run_chat
from app.agent.planning import LlmPlanner, ensure_plan
from app.agent.state import AgentState, InMemoryStateStore
from app.config import Settings
from app.core.logging import StructuredFormatter, setup_logging
from app.core.metrics import MetricsSnapshot, session_metrics
from app.core.tracing import set_trace_id
from app.main import app, create_app
from app.models.agent import Language, ToolCallRecord


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


def test_metrics_snapshot_tracks_turn_deltas() -> None:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    snapshot = MetricsSnapshot(state)

    state.llm_call_count = 1
    state.token_usage = 150
    state.tool_history.append(
        ToolCallRecord(
            tool="flight",
            action="search_flights",
            status="completed",
            step_id="search",
        )
    )

    turn = snapshot.turn_metrics(state, latency_ms=42.5)
    session = session_metrics(state)

    assert turn.latency_ms == 42.5
    assert turn.tool_call_count == 1
    assert turn.llm_call_count == 1
    assert turn.token_usage == 150
    assert session.tool_call_count == 1
    assert session.llm_call_count == 1
    assert session.token_usage == 150


def test_llm_planner_records_token_usage_on_state() -> None:
    mock_client = MagicMock()
    mock_block = MagicMock(
        type="text",
        text='{"goal": "Find flights", "steps": [{"id": "search", "worker": "flight", "action": "search_flights", "depends_on": []}]}',
    )
    mock_response = MagicMock(
        content=[mock_block],
        usage=MagicMock(input_tokens=120, output_tokens=80),
    )
    mock_client.messages.create.return_value = mock_response

    planner = LlmPlanner(
        settings=Settings(anthropic_api_key="test-key", planner_use_mock=False),
        client=mock_client,
    )
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.user_message = "Find flights TIA to FRA"
    state.language = Language.EN

    planner.create_plan(state)

    assert state.token_usage == 200


def test_ensure_plan_increments_llm_and_token_counters() -> None:
    mock_client = MagicMock()
    mock_block = MagicMock(
        type="text",
        text='{"goal": "Find flights", "steps": [{"id": "search", "worker": "flight", "action": "search_flights", "depends_on": []}]}',
    )
    mock_response = MagicMock(
        content=[mock_block],
        usage=MagicMock(input_tokens=50, output_tokens=25),
    )
    mock_client.messages.create.return_value = mock_response

    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.user_message = "Find flights TIA to FRA"

    ensure_plan(
        state,
        planner=LlmPlanner(
            settings=Settings(anthropic_api_key="test-key", planner_use_mock=False),
            client=mock_client,
        ),
    )

    assert state.llm_call_count == 1
    assert state.token_usage == 75
    assert len(state.plan.steps) == 1


def test_run_chat_logs_turn_metrics(log_capture: io.StringIO) -> None:
    set_trace_id("trace-metrics-1")
    store = InMemoryStateStore()

    run_chat(
        user_message="Find flights TIA to FRA on 2025-09-15",
        trace_id="trace-metrics-1",
        conversation_id="conv-metrics",
        store=store,
    )

    records = [json.loads(line) for line in log_capture.getvalue().strip().splitlines()]
    metrics_log = next(record for record in records if record.get("event") == "turn_metrics")

    assert metrics_log["trace_id"] == "trace-metrics-1"
    assert metrics_log["latency_ms"] >= 0.0
    assert metrics_log["turn_tool_call_count"] >= 1
    assert metrics_log["tool_call_count"] >= 1
    assert metrics_log["llm_call_count"] == 0
    assert metrics_log["token_usage"] == 0


def test_chat_response_log_includes_session_metrics(log_capture: io.StringIO, tmp_path) -> None:
    db_path = tmp_path / "bookings.db"
    settings = Settings(
        flight_api_use_mock=True,
        planner_use_mock=True,
        nlu_use_mock=True,
        booking_db_path=str(db_path),
    )
    client = TestClient(create_app(settings))
    response = client.post("/chat", json={"message": "Find flights TIA to FRA on 2025-09-15"})

    assert response.status_code == 200

    records = [json.loads(line) for line in log_capture.getvalue().strip().splitlines()]
    chat_log = next(record for record in records if record.get("event") == "chat_response")

    assert chat_log["tool_call_count"] >= 1
    assert chat_log["llm_call_count"] == 0
    assert chat_log["token_usage"] == 0
    assert chat_log["iteration_count"] == 1
