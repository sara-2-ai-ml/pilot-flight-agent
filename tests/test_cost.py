"""Cost tracking tests — Phase 10.5."""

import io
import json
import logging
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.agent.loop import run_chat
from app.agent.planning import LlmPlanner
from app.agent.state import AgentState, InMemoryStateStore
from app.config import Settings, get_settings
from app.core.cost import build_cost_debug_payload, session_cost, turn_cost
from app.core.logging import StructuredFormatter, setup_logging
from app.core.metrics import MetricsSnapshot
from app.core.tracing import set_trace_id
from app.main import create_app


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


def test_session_cost_reads_state_counters() -> None:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.llm_call_count = 2
    state.token_usage = 350

    cost = session_cost(state)

    assert cost.llm_call_count == 2
    assert cost.token_usage == 350


def test_turn_cost_extracts_turn_metrics() -> None:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    snapshot = MetricsSnapshot(state)
    state.llm_call_count = 1
    state.token_usage = 75
    turn = snapshot.turn_metrics(state, latency_ms=10.0)

    cost = turn_cost(turn)

    assert cost.llm_call_count == 1
    assert cost.token_usage == 75


def test_build_cost_debug_payload_includes_session_and_turn() -> None:
    from app.core.cost import CostSummary

    payload = build_cost_debug_payload(
        session=CostSummary(llm_call_count=3, token_usage=500),
        turn=CostSummary(llm_call_count=1, token_usage=120),
    )

    assert payload == {
        "session": {"llm_call_count": 3, "token_usage": 500},
        "turn": {"llm_call_count": 1, "token_usage": 120},
    }


def test_run_chat_logs_cost_tracking(log_capture: io.StringIO) -> None:
    set_trace_id("trace-cost-1")
    store = InMemoryStateStore()

    run_chat(
        user_message="Find flights TIA to FRA on 2025-09-15",
        trace_id="trace-cost-1",
        conversation_id="conv-cost",
        store=store,
    )

    records = [json.loads(line) for line in log_capture.getvalue().strip().splitlines()]
    cost_log = next(record for record in records if record.get("event") == "cost_tracking")

    assert cost_log["trace_id"] == "trace-cost-1"
    assert cost_log["llm_call_count"] == 0
    assert cost_log["token_usage"] == 0
    assert cost_log["turn_llm_call_count"] == 0
    assert cost_log["turn_token_usage"] == 0


def test_run_chat_cost_tracking_reflects_llm_usage(log_capture: io.StringIO) -> None:
    mock_client = MagicMock()
    mock_block = MagicMock(
        type="text",
        text='{"goal": "Find flights", "steps": [{"id": "search", "worker": "flight", "action": "search_flights", "depends_on": []}]}',
    )
    mock_response = MagicMock(
        content=[mock_block],
        usage=MagicMock(input_tokens=100, output_tokens=40),
    )
    mock_client.messages.create.return_value = mock_response

    store = InMemoryStateStore()
    run_chat(
        user_message="Find flights TIA to FRA on 2025-09-15",
        trace_id="trace-cost-llm",
        conversation_id="conv-cost-llm",
        store=store,
        settings=Settings(planner_use_mock=False, anthropic_api_key="test-key"),
        planner=LlmPlanner(
            settings=Settings(planner_use_mock=False, anthropic_api_key="test-key"),
            client=mock_client,
        ),
    )

    records = [json.loads(line) for line in log_capture.getvalue().strip().splitlines()]
    cost_log = next(record for record in records if record.get("event") == "cost_tracking")

    assert cost_log["llm_call_count"] == 1
    assert cost_log["token_usage"] == 140
    assert cost_log["turn_llm_call_count"] == 1
    assert cost_log["turn_token_usage"] == 140


def test_chat_omits_debug_when_debug_disabled() -> None:
    app = create_app(Settings(debug=False))
    client = TestClient(app)
    response = client.post("/chat", json={"message": "Find flights TIA to FRA"})

    assert response.status_code == 200
    assert "debug" not in response.json()


def test_chat_includes_cost_debug_when_debug_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEBUG", "true")
    get_settings.cache_clear()
    app = create_app(get_settings())
    client = TestClient(app)

    response = client.post("/chat", json={"message": "Find flights TIA to FRA on 2025-09-15"})

    assert response.status_code == 200
    body = response.json()
    assert body["debug"]["cost"]["session"]["llm_call_count"] == 0
    assert body["debug"]["cost"]["session"]["token_usage"] == 0

    get_settings.cache_clear()
