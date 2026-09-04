"""Request tracing — trace_id and nested spans across agent lifecycle."""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Iterator

import time

_trace_id: ContextVar[str | None] = ContextVar("trace_id", default=None)
_spans: ContextVar[list[SpanRecord] | None] = ContextVar("trace_spans", default=None)
_span_stack: ContextVar[list[str] | None] = ContextVar("span_stack", default=None)


@dataclass
class SpanRecord:
    """One timed operation within a request trace."""

    span_id: str
    parent_span_id: str | None
    name: str
    kind: str
    started_at: float
    attributes: dict[str, Any] = field(default_factory=dict)
    ended_at: float | None = None
    latency_ms: float | None = None
    status: str = "ok"

    def mark_error(self) -> None:
        self.status = "error"


def generate_trace_id() -> str:
    """Create a unique trace id for one request lifecycle."""
    return uuid.uuid4().hex


def set_trace_id(trace_id: str) -> None:
    """Bind trace id to the current request context."""
    _trace_id.set(trace_id)


def get_trace_id() -> str | None:
    """Return trace id for the current request, if set."""
    return _trace_id.get()


def _generate_span_id() -> str:
    return uuid.uuid4().hex[:16]


def _get_spans() -> list[SpanRecord]:
    spans = _spans.get()
    if spans is None:
        spans = []
        _spans.set(spans)
    return spans


def _get_span_stack() -> list[str]:
    stack = _span_stack.get()
    if stack is None:
        stack = []
        _span_stack.set(stack)
    return stack


def reset_trace_context() -> None:
    """Clear span collection for a new request lifecycle."""
    _spans.set([])
    _span_stack.set([])


def get_trace_spans() -> list[SpanRecord]:
    """Return span records collected for the current request."""
    return list(_get_spans())


def current_span_id() -> str | None:
    """Return the innermost active span id, if any."""
    stack = _span_stack.get()
    if not stack:
        return None
    return stack[-1]


@contextmanager
def trace_span(name: str, *, kind: str, **attributes: Any) -> Iterator[SpanRecord]:
    """Open a timed span; nested spans attach to the current parent."""
    span_id = _generate_span_id()
    parent_span_id = current_span_id()
    stack = _get_span_stack()
    stack.append(span_id)

    record = SpanRecord(
        span_id=span_id,
        parent_span_id=parent_span_id,
        name=name,
        kind=kind,
        started_at=time.perf_counter(),
        attributes={key: value for key, value in attributes.items() if value is not None},
    )
    _get_spans().append(record)

    try:
        yield record
    except Exception:
        record.mark_error()
        raise
    finally:
        record.ended_at = time.perf_counter()
        record.latency_ms = round((record.ended_at - record.started_at) * 1000, 2)
        if stack and stack[-1] == span_id:
            stack.pop()


def _span_node(record: SpanRecord) -> dict[str, Any]:
    return {
        "span_id": record.span_id,
        "name": record.name,
        "kind": record.kind,
        "status": record.status,
        "latency_ms": record.latency_ms,
        "attributes": record.attributes,
        "children": [],
    }


def build_trace_tree(spans: list[SpanRecord] | None = None) -> list[dict[str, Any]]:
    """Build a nested trace tree from flat span records."""
    resolved = spans if spans is not None else get_trace_spans()
    nodes = {span.span_id: _span_node(span) for span in resolved}
    roots: list[dict[str, Any]] = []

    for span in resolved:
        node = nodes[span.span_id]
        if span.parent_span_id and span.parent_span_id in nodes:
            nodes[span.parent_span_id]["children"].append(node)
        else:
            roots.append(node)

    return roots


def format_trace_tree(spans: list[SpanRecord] | None = None) -> str:
    """Render a human-readable trace tree for logs and debugging."""
    tree = build_trace_tree(spans)
    lines: list[str] = []

    def render(nodes: list[dict[str, Any]], depth: int = 0) -> None:
        for node in nodes:
            indent = "  " * depth
            latency = node.get("latency_ms")
            latency_text = f"{latency}ms" if latency is not None else "?ms"
            lines.append(
                f"{indent}{node['name']} "
                f"[{node['kind']}, {latency_text}, {node['status']}]"
            )
            render(node["children"], depth + 1)

    render(tree)
    return "\n".join(lines)
