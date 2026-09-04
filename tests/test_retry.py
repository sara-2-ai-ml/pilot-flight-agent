"""Retry helper tests — Phase 9.1."""

from __future__ import annotations

import pytest

from app.core.retry import (
    RetryExhaustedError,
    RetryPolicy,
    compute_backoff_delay,
    retry_with_backoff,
)


def test_compute_backoff_delay_uses_exponential_backoff() -> None:
    assert compute_backoff_delay(1, base_delay_seconds=0.5, max_delay_seconds=4.0) == 0.5
    assert compute_backoff_delay(2, base_delay_seconds=0.5, max_delay_seconds=4.0) == 1.0
    assert compute_backoff_delay(3, base_delay_seconds=0.5, max_delay_seconds=4.0) == 2.0


def test_compute_backoff_delay_respects_max_delay() -> None:
    assert compute_backoff_delay(5, base_delay_seconds=0.5, max_delay_seconds=1.0) == 1.0


def test_retry_with_backoff_succeeds_on_first_attempt() -> None:
    calls = {"count": 0}

    def operation() -> str:
        calls["count"] += 1
        return "ok"

    result = retry_with_backoff(
        operation,
        policy=RetryPolicy(max_attempts=3, base_delay_seconds=0.01, max_delay_seconds=0.01),
    )

    assert result == "ok"
    assert calls["count"] == 1


def test_retry_with_backoff_retries_flaky_operation_then_succeeds() -> None:
    calls = {"count": 0}
    delays: list[float] = []

    def operation() -> str:
        calls["count"] += 1
        if calls["count"] < 3:
            raise RuntimeError("temporary failure")
        return "ok"

    result = retry_with_backoff(
        operation,
        policy=RetryPolicy(max_attempts=3, base_delay_seconds=0.01, max_delay_seconds=0.01),
        sleep=delays.append,
    )

    assert result == "ok"
    assert calls["count"] == 3
    assert delays == [0.01, 0.01]


def test_retry_with_backoff_raises_after_max_attempts() -> None:
    calls = {"count": 0}

    def operation() -> str:
        calls["count"] += 1
        raise RuntimeError("still failing")

    with pytest.raises(RetryExhaustedError, match="3 attempts") as exc_info:
        retry_with_backoff(
            operation,
            policy=RetryPolicy(max_attempts=3, base_delay_seconds=0.01, max_delay_seconds=0.01),
            sleep=lambda _delay: None,
        )

    assert calls["count"] == 3
    assert isinstance(exc_info.value.last_error, RuntimeError)


def test_retry_with_backoff_skips_non_retryable_errors() -> None:
    calls = {"count": 0}

    def operation() -> str:
        calls["count"] += 1
        raise ValueError("permanent failure")

    with pytest.raises(RetryExhaustedError):
        retry_with_backoff(
            operation,
            policy=RetryPolicy(max_attempts=3, base_delay_seconds=0.01, max_delay_seconds=0.01),
            is_retryable=lambda exc: isinstance(exc, RuntimeError),
            sleep=lambda _delay: None,
        )

    assert calls["count"] == 1


def test_retry_with_backoff_can_be_disabled() -> None:
    calls = {"count": 0}

    def operation() -> str:
        calls["count"] += 1
        raise RuntimeError("fail once")

    with pytest.raises(RuntimeError):
        retry_with_backoff(
            operation,
            policy=RetryPolicy(enabled=False, max_attempts=3),
        )

    assert calls["count"] == 1
