"""In-memory rate limiting — Phase 8.3."""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass
from threading import Lock

from app.config import Settings, get_settings


@dataclass(frozen=True)
class RateLimitResult:
    """Outcome of one rate-limit check."""

    allowed: bool
    retry_after_seconds: int | None = None


class InMemoryRateLimiter:
    """Fixed-window request counter keyed by arbitrary bucket ids."""

    def __init__(self) -> None:
        self._events: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()

    def clear(self) -> None:
        with self._lock:
            self._events.clear()

    def check(
        self,
        key: str,
        *,
        limit: int,
        window_seconds: float,
    ) -> RateLimitResult:
        now = time.monotonic()
        window_start = now - window_seconds

        with self._lock:
            timestamps = [stamp for stamp in self._events[key] if stamp > window_start]
            if len(timestamps) >= limit:
                retry_after = max(1, int(window_seconds - (now - timestamps[0])) + 1)
                self._events[key] = timestamps
                return RateLimitResult(allowed=False, retry_after_seconds=retry_after)

            timestamps.append(now)
            self._events[key] = timestamps
            return RateLimitResult(allowed=True)


_default_limiter = InMemoryRateLimiter()


def get_rate_limiter() -> InMemoryRateLimiter:
    return _default_limiter


def reset_rate_limiter() -> None:
    """Clear all counters — for tests."""
    _default_limiter.clear()


def check_ip_rate_limit(
    client_ip: str,
    *,
    settings: Settings | None = None,
) -> RateLimitResult:
    resolved = settings or get_settings()
    if not resolved.rate_limit_enabled:
        return RateLimitResult(allowed=True)

    return get_rate_limiter().check(
        f"ip:{client_ip}",
        limit=resolved.rate_limit_ip_requests,
        window_seconds=resolved.rate_limit_window_seconds,
    )


def check_conversation_rate_limit(
    conversation_id: str,
    *,
    settings: Settings | None = None,
) -> RateLimitResult:
    resolved = settings or get_settings()
    if not resolved.rate_limit_enabled:
        return RateLimitResult(allowed=True)

    normalized = conversation_id.strip()
    if not normalized:
        return RateLimitResult(allowed=True)

    return get_rate_limiter().check(
        f"conversation:{normalized}",
        limit=resolved.rate_limit_conversation_requests,
        window_seconds=resolved.rate_limit_window_seconds,
    )
