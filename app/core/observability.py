"""Structured observability helpers — trace_id, step, latency."""

import time
from typing import Any

from app.core.tracing import get_trace_id


def log_extra(**fields: Any) -> dict[str, Any]:
    """Build logger ``extra`` with ``trace_id`` from request context when set."""
    extra = dict(fields)
    if "trace_id" not in extra:
        trace_id = get_trace_id()
        if trace_id is not None:
            extra["trace_id"] = trace_id
    return {key: value for key, value in extra.items() if value is not None}


def elapsed_ms(start: float) -> float:
    """Return milliseconds elapsed since ``start`` from ``time.perf_counter()``."""
    return round((time.perf_counter() - start) * 1000, 2)
