"""External call timeouts."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.config import Settings, get_settings


class ExternalCallTimeoutError(TimeoutError):
    """Raised when an external dependency exceeds its configured timeout."""


def httpx_timeout_from_settings(settings: Settings | None = None) -> httpx.Timeout:
    """Build an httpx timeout from application settings."""
    resolved = settings or get_settings()
    seconds = resolved.external_http_timeout_seconds
    return httpx.Timeout(seconds)


async def await_with_timeout(
    coro: Any,
    *,
    timeout_seconds: float,
    operation: str,
) -> Any:
    """Await one coroutine and fail fast when it exceeds ``timeout_seconds``."""
    try:
        return await asyncio.wait_for(coro, timeout=timeout_seconds)
    except asyncio.TimeoutError as exc:
        raise ExternalCallTimeoutError(
            f"{operation} timed out after {timeout_seconds} seconds.",
        ) from exc


def run_with_timeout(
    coro: Any,
    *,
    timeout_seconds: float,
    operation: str,
) -> Any:
    """Run one coroutine from synchronous code with a timeout."""

    async def _run() -> Any:
        return await await_with_timeout(
            coro,
            timeout_seconds=timeout_seconds,
            operation=operation,
        )

    return asyncio.run(_run())
