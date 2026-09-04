"""Circuit breaker — fail fast after repeated failures."""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from threading import Lock

from app.config import Settings, get_settings


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"


class CircuitBreakerOpenError(Exception):
    """Raised when a circuit is open and calls must fail fast."""

    def __init__(
        self,
        message: str,
        *,
        circuit: str,
        retry_after_seconds: float | None = None,
    ) -> None:
        self.circuit = circuit
        self.retry_after_seconds = retry_after_seconds
        super().__init__(message)


@dataclass(frozen=True)
class CircuitBreakerPolicy:
    """Circuit breaker limits loaded from application settings."""

    enabled: bool = True
    failure_threshold: int = 5
    window_seconds: float = 60.0
    open_seconds: float = 30.0

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> CircuitBreakerPolicy:
        resolved = settings or get_settings()
        return cls(
            enabled=resolved.circuit_breaker_enabled,
            failure_threshold=resolved.circuit_breaker_failure_threshold,
            window_seconds=resolved.circuit_breaker_window_seconds,
            open_seconds=resolved.circuit_breaker_open_seconds,
        )


class InMemoryCircuitBreaker:
    """Track failures in a sliding window and open circuits after a threshold."""

    def __init__(self) -> None:
        self._states: dict[str, CircuitState] = {}
        self._failures: dict[str, list[float]] = defaultdict(list)
        self._opened_at: dict[str, float] = {}
        self._lock = Lock()

    def clear(self) -> None:
        with self._lock:
            self._states.clear()
            self._failures.clear()
            self._opened_at.clear()

    def is_open(self, circuit: str, *, policy: CircuitBreakerPolicy | None = None) -> bool:
        resolved = policy or CircuitBreakerPolicy.from_settings()
        if not resolved.enabled:
            return False

        now = time.monotonic()
        with self._lock:
            if self._states.get(circuit) != CircuitState.OPEN:
                return False
            opened_at = self._opened_at.get(circuit, now)
            return now - opened_at < resolved.open_seconds

    def allow(self, circuit: str, policy: CircuitBreakerPolicy) -> None:
        """Reject the call when the circuit is open."""
        if not policy.enabled:
            return

        now = time.monotonic()
        with self._lock:
            if self._states.get(circuit) != CircuitState.OPEN:
                return

            opened_at = self._opened_at[circuit]
            elapsed = now - opened_at
            if elapsed < policy.open_seconds:
                retry_after = max(0.0, policy.open_seconds - elapsed)
                raise CircuitBreakerOpenError(
                    f"Circuit '{circuit}' is open; failing fast.",
                    circuit=circuit,
                    retry_after_seconds=retry_after,
                )

            self._states[circuit] = CircuitState.CLOSED
            self._failures[circuit] = []
            self._opened_at.pop(circuit, None)

    def record_success(self, circuit: str) -> None:
        with self._lock:
            self._states[circuit] = CircuitState.CLOSED
            self._failures[circuit] = []
            self._opened_at.pop(circuit, None)

    def record_failure(self, circuit: str, policy: CircuitBreakerPolicy) -> None:
        if not policy.enabled:
            return

        now = time.monotonic()
        window_start = now - policy.window_seconds

        with self._lock:
            failures = [stamp for stamp in self._failures[circuit] if stamp > window_start]
            failures.append(now)
            self._failures[circuit] = failures
            if len(failures) >= policy.failure_threshold:
                self._states[circuit] = CircuitState.OPEN
                self._opened_at[circuit] = now


_default_breaker = InMemoryCircuitBreaker()


def get_circuit_breaker() -> InMemoryCircuitBreaker:
    return _default_breaker


def reset_circuit_breaker() -> None:
    _default_breaker.clear()
