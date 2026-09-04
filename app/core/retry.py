"""Retry with exponential backoff."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from app.config import Settings, get_settings

T = TypeVar("T")


class RetryExhaustedError(Exception):
    """Raised when an operation fails after all retry attempts."""

    def __init__(
        self,
        message: str,
        *,
        attempts: int,
        last_error: BaseException | None = None,
    ) -> None:
        self.attempts = attempts
        self.last_error = last_error
        super().__init__(message)


@dataclass(frozen=True)
class RetryPolicy:
    """Retry limits loaded from application settings."""

    enabled: bool = True
    max_attempts: int = 3
    base_delay_seconds: float = 0.5
    max_delay_seconds: float = 4.0

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> RetryPolicy:
        resolved = settings or get_settings()
        return cls(
            enabled=resolved.retry_enabled,
            max_attempts=resolved.retry_max_attempts,
            base_delay_seconds=resolved.retry_base_delay_seconds,
            max_delay_seconds=resolved.retry_max_delay_seconds,
        )


def compute_backoff_delay(
    attempt: int,
    *,
    base_delay_seconds: float,
    max_delay_seconds: float,
) -> float:
    """Return the delay before retry attempt ``attempt`` (1-based)."""
    return min(base_delay_seconds * (2 ** (attempt - 1)), max_delay_seconds)


def retry_with_backoff(
    operation: Callable[[], T],
    *,
    policy: RetryPolicy | None = None,
    is_retryable: Callable[[BaseException], bool] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    on_retry: Callable[[int, BaseException, float], None] | None = None,
) -> T:
    """Run ``operation`` with exponential backoff until success or attempts are exhausted."""
    resolved = policy or RetryPolicy.from_settings()
    if not resolved.enabled:
        return operation()

    last_error: BaseException | None = None
    for attempt in range(1, resolved.max_attempts + 1):
        try:
            return operation()
        except BaseException as exc:
            last_error = exc
            retryable = is_retryable(exc) if is_retryable is not None else True
            if attempt >= resolved.max_attempts or not retryable:
                break

            delay = compute_backoff_delay(
                attempt,
                base_delay_seconds=resolved.base_delay_seconds,
                max_delay_seconds=resolved.max_delay_seconds,
            )
            if on_retry is not None:
                on_retry(attempt, exc, delay)
            sleep(delay)

    raise RetryExhaustedError(
        f"Operation failed after {resolved.max_attempts} attempts.",
        attempts=resolved.max_attempts,
        last_error=last_error,
    ) from last_error
