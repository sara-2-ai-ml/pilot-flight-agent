"""HTTP middleware."""

import time
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.logging import get_logger
from app.core.observability import elapsed_ms, log_extra
from app.core.tracing import (
    build_trace_tree,
    format_trace_tree,
    generate_trace_id,
    get_trace_spans,
    reset_trace_context,
    set_trace_id,
    trace_span,
)
from app.guardrails.rate_limit import check_ip_rate_limit

logger = get_logger("http")

_RATE_LIMITED_PREFIXES = ("/chat", "/approvals")


def client_ip_from_request(request: Request) -> str:
    """Resolve the client IP, honoring X-Forwarded-For when present."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",", maxsplit=1)[0].strip()
    if request.client is not None and request.client.host:
        return request.client.host
    return "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Apply per-IP rate limits before request handlers run."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        settings = request.app.state.settings
        path = request.url.path

        if (
            settings.rate_limit_enabled
            and path != "/health"
            and any(path.startswith(prefix) for prefix in _RATE_LIMITED_PREFIXES)
        ):
            result = check_ip_rate_limit(client_ip_from_request(request), settings=settings)
            if not result.allowed:
                retry_after = result.retry_after_seconds or 1
                logger.warning(
                    "rate_limit_exceeded",
                    extra={
                        "event": "rate_limit_exceeded",
                        "scope": "ip",
                        "path": path,
                        "client_ip": client_ip_from_request(request),
                        "retry_after_seconds": retry_after,
                    },
                )
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too many requests. Please try again later."},
                    headers={"Retry-After": str(retry_after)},
                )

        return await call_next(request)


class TraceMiddleware(BaseHTTPMiddleware):
    """Assign trace_id per request and emit request lifecycle logs."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        trace_id = request.headers.get("X-Trace-Id") or generate_trace_id()
        set_trace_id(trace_id)
        reset_trace_context()
        started_at = time.perf_counter()

        logger.info(
            "request_started",
            extra=log_extra(
                trace_id=trace_id,
                event="request_started",
                method=request.method,
                path=request.url.path,
            ),
        )

        with trace_span(
            f"{request.method} {request.url.path}",
            kind="request",
            method=request.method,
            path=request.url.path,
        ):
            response = await call_next(request)
        response.headers["X-Trace-Id"] = trace_id

        logger.info(
            "request_completed",
            extra=log_extra(
                trace_id=trace_id,
                event="request_completed",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                latency_ms=elapsed_ms(started_at),
                trace_tree=build_trace_tree(get_trace_spans()),
                trace_tree_text=format_trace_tree(get_trace_spans()),
            ),
        )

        return response
