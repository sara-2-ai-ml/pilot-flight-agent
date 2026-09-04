"""Span tracing tests — Phase 10.2."""

import io
import json
import logging

import pytest
from fastapi.testclient import TestClient

from app.agent.coordinator import execute_step, select_current_step
from app.agent.planning import ensure_plan
from app.agent.state import AgentState
from app.core.logging import StructuredFormatter, setup_logging
from app.core.tracing import (
    build_trace_tree,
    format_trace_tree,
    get_trace_spans,
    reset_trace_context,
    set_trace_id,
    trace_span,
)
from app.main import app


@pytest.fixture(autouse=True)
def isolated_trace_context() -> None:
    reset_trace_context()
    yield
    reset_trace_context()


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


def test_trace_span_records_parent_child_relationship() -> None:
    with trace_span("request", kind="request"):
        with trace_span("create_plan", kind="plan"):
            with trace_span("worker:search", kind="worker"):
                with trace_span("tool:search_flights", kind="tool"):
                    pass

    spans = get_trace_spans()
    by_name = {span.name: span for span in spans}

    assert by_name["tool:search_flights"].parent_span_id == by_name["worker:search"].span_id
    assert by_name["worker:search"].parent_span_id == by_name["create_plan"].span_id
    assert by_name["create_plan"].parent_span_id == by_name["request"].span_id
    assert all(span.latency_ms is not None for span in spans)


def test_build_trace_tree_nests_children() -> None:
    with trace_span("request", kind="request"):
        with trace_span("worker:search", kind="worker"):
            with trace_span("tool:search_flights", kind="tool"):
                pass

    tree = build_trace_tree()
    assert len(tree) == 1
    assert tree[0]["name"] == "request"
    assert tree[0]["children"][0]["name"] == "worker:search"
    assert tree[0]["children"][0]["children"][0]["name"] == "tool:search_flights"


def test_format_trace_tree_is_human_readable() -> None:
    with trace_span("request", kind="request"):
        with trace_span("worker:search", kind="worker"):
            pass

    rendered = format_trace_tree()
    lines = rendered.splitlines()

    assert lines[0].startswith("request [request,")
    assert lines[1].startswith("  worker:search [worker,")


def test_execute_step_collects_worker_and_tool_spans() -> None:
    set_trace_id("trace-span-1")
    state = AgentState.new(conversation_id="conv1", trace_id="trace-span-1")
    state.user_message = "Find flights TIA to FRA on Sep 15"

    with trace_span("POST /chat", kind="request"):
        ensure_plan(state)
        step = select_current_step(state)
        assert step is not None
        execute_step(state, step)

    kinds = [span.kind for span in get_trace_spans()]
    names = [span.name for span in get_trace_spans()]

    assert "plan" in kinds
    assert "worker" in kinds
    assert "tool" in kinds
    assert "create_plan" in names
    assert "worker:search" in names
    assert "tool:search_flights" in names


def test_chat_request_logs_readable_trace_tree(log_capture: io.StringIO) -> None:
    client = TestClient(app)
    response = client.post("/chat", json={"message": "Find flights TIA to FRA on 2025-09-15"})

    assert response.status_code == 200

    records = [json.loads(line) for line in log_capture.getvalue().strip().splitlines()]
    completed = next(record for record in records if record.get("event") == "request_completed")

    trace_tree = completed["trace_tree"]
    trace_tree_text = completed["trace_tree_text"]

    assert trace_tree[0]["kind"] == "request"
    child_kinds = {child["kind"] for child in trace_tree[0]["children"]}
    assert "plan" in child_kinds
    assert "worker" in child_kinds

    worker_node = next(
        child for child in trace_tree[0]["children"] if child["kind"] == "worker"
    )
    assert worker_node["name"] == "worker:search"
    assert worker_node["children"][0]["kind"] == "tool"
    assert worker_node["children"][0]["name"] == "tool:search_flights"

    assert "POST /chat [request," in trace_tree_text
    assert "create_plan [plan," in trace_tree_text
    assert "worker:search [worker," in trace_tree_text
    assert "tool:search_flights [tool," in trace_tree_text
