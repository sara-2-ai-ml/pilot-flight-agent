"""Structured logging."""

import json
import logging
from datetime import UTC, datetime

from app.config import get_settings
from app.core.tracing import get_trace_id
from app.guardrails.pii import redact_pii, redact_pii_in_mapping

_LOG_RECORD_SKIP = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "module",
    "msecs",
    "message",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "taskName",
    "thread",
    "threadName",
}


class StructuredFormatter(logging.Formatter):
    """Emit one JSON object per log line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        for key, value in record.__dict__.items():
            if key not in _LOG_RECORD_SKIP and value is not None:
                payload[key] = value

        if "trace_id" not in payload:
            trace_id = get_trace_id()
            if trace_id is not None:
                payload["trace_id"] = trace_id

        settings = get_settings()
        payload["message"] = redact_pii(payload["message"], settings=settings).text
        payload = redact_pii_in_mapping(payload, settings=settings)

        return json.dumps(payload, ensure_ascii=False)


def setup_logging(level: str = "INFO") -> None:
    """Configure the application logger tree once."""
    app_logger = logging.getLogger("app")
    app_logger.setLevel(level.upper())

    if app_logger.handlers:
        return

    handler = logging.StreamHandler()
    handler.setFormatter(StructuredFormatter())
    app_logger.addHandler(handler)
    app_logger.propagate = False


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced application logger."""
    return logging.getLogger(f"app.{name}")
