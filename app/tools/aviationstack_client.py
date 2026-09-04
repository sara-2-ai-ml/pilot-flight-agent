"""AviationStack HTTP client — access_key query auth, no OAuth."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

import httpx

from app.config import Settings, get_settings
from app.core.circuit_breaker import (
    CircuitBreakerOpenError,
    CircuitBreakerPolicy,
    get_circuit_breaker,
)
from app.core.errors import ErrorCode
from app.core.logging import get_logger
from app.core.retry import RetryExhaustedError, RetryPolicy, retry_with_backoff
from app.core.timeout import httpx_timeout_from_settings
from app.models.flight import (
    FlightOption,
    FlightStatusInfo,
    normalize_aviationstack_flights_payload,
    normalize_aviationstack_status_payload,
)
from app.tools.flight_client import FlightApiError

T = TypeVar("T")

_JSON_HEADERS = {"Accept": "application/json"}
_RETRYABLE_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})
_AVIATIONSTACK_CIRCUIT = "aviationstack_api"
_logger = get_logger("tools.aviationstack")


class AviationStackApiError(Exception):
    """Raised when the AviationStack API returns an error or cannot be reached."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        code: str | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        super().__init__(message)


def is_aviationstack_retryable_error(exc: BaseException) -> bool:
    """Return True when an AviationStack request should be retried."""
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, AviationStackApiError):
        return exc.status_code in _RETRYABLE_STATUS_CODES
    return False


def is_aviationstack_circuit_failure(exc: BaseException) -> bool:
    """Return True when a failure should count toward the circuit breaker."""
    if isinstance(exc, CircuitBreakerOpenError):
        return False
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, AviationStackApiError):
        if exc.status_code is None:
            return True
        return exc.status_code in _RETRYABLE_STATUS_CODES
    return False


class AviationStackClient:
    """Thin HTTP wrapper for AviationStack flight endpoints."""

    def __init__(
        self,
        settings: Settings | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._owns_client = http_client is None
        self._http = http_client or httpx.Client(
            base_url=self._settings.flight_api_base_url.rstrip("/"),
            timeout=httpx_timeout_from_settings(self._settings),
        )

    def close(self) -> None:
        if self._owns_client:
            self._http.close()

    def __enter__(self) -> AviationStackClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _require_access_key(self) -> str:
        access_key = self._settings.flight_api_key
        if not access_key:
            raise AviationStackApiError("Flight API access key is not configured.")
        return access_key

    def _call_with_retry(self, operation: Callable[[], T]) -> T:
        policy = RetryPolicy.from_settings(self._settings)

        def _on_retry(attempt: int, exc: BaseException, delay: float) -> None:
            _logger.warning(
                "aviationstack_request_retry",
                extra={
                    "event": "aviationstack_request_retry",
                    "attempt": attempt,
                    "delay_seconds": delay,
                    "error": str(exc),
                },
            )

        try:
            return retry_with_backoff(
                operation,
                policy=policy,
                is_retryable=is_aviationstack_retryable_error,
                on_retry=_on_retry,
            )
        except RetryExhaustedError as exc:
            if exc.last_error is not None:
                raise exc.last_error from exc
            raise AviationStackApiError(
                "AviationStack API request failed after retries.",
            ) from exc

    def _call_with_reliability(self, operation: Callable[[], T]) -> T:
        breaker = get_circuit_breaker()
        breaker_policy = CircuitBreakerPolicy.from_settings(self._settings)

        try:
            breaker.allow(_AVIATIONSTACK_CIRCUIT, breaker_policy)
        except CircuitBreakerOpenError as exc:
            _logger.warning(
                "aviationstack_circuit_open",
                extra={
                    "event": "aviationstack_circuit_open",
                    "circuit": exc.circuit,
                    "retry_after_seconds": exc.retry_after_seconds,
                },
            )
            raise AviationStackApiError(
                "Flight API circuit breaker is open; failing fast.",
                code=ErrorCode.CIRCUIT_OPEN.value,
            ) from exc

        try:
            result = self._call_with_retry(operation)
        except BaseException as exc:
            if is_aviationstack_circuit_failure(exc):
                breaker.record_failure(_AVIATIONSTACK_CIRCUIT, breaker_policy)
            raise

        breaker.record_success(_AVIATIONSTACK_CIRCUIT)
        return result

    def _request_json(
        self,
        *,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        def _request() -> dict[str, Any]:
            query = {"access_key": self._require_access_key(), **params}
            try:
                response = self._http.get(
                    "/flights",
                    headers=_JSON_HEADERS,
                    params=query,
                )
            except httpx.TimeoutException as exc:
                raise AviationStackApiError(
                    "AviationStack API request timed out "
                    f"after {self._settings.external_http_timeout_seconds} seconds.",
                ) from exc

            if response.status_code >= 400:
                raise AviationStackApiError(
                    "AviationStack API request failed.",
                    status_code=response.status_code,
                )

            payload = response.json()
            if not isinstance(payload, dict):
                raise AviationStackApiError("AviationStack API returned unexpected payload.")

            error = payload.get("error")
            if isinstance(error, dict):
                message = error.get("message") or error.get("info") or "AviationStack API error."
                raise AviationStackApiError(str(message), code=str(error.get("code") or ""))

            return payload

        return self._call_with_reliability(_request)

    def get_flights(
        self,
        *,
        dep_iata: str | None = None,
        arr_iata: str | None = None,
        flight_date: str | None = None,
        flight_iata: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Fetch flights filtered by route, date, or flight number."""
        params: dict[str, Any] = {"limit": limit}
        if dep_iata:
            params["dep_iata"] = dep_iata.upper()
        if arr_iata:
            params["arr_iata"] = arr_iata.upper()
        if flight_date:
            params["flight_date"] = flight_date
        if flight_iata:
            params["flight_iata"] = flight_iata.replace(" ", "").upper()
        return self._request_json(params=params)


def create_aviationstack_client(
    *,
    settings: Settings | None = None,
    http_client: httpx.Client | None = None,
) -> AviationStackClient:
    """Build a client instance for dependency injection in tests and services."""
    return AviationStackClient(settings=settings, http_client=http_client)


class AviationStackFlightApiClient:
    """AviationStack-backed FlightApiClient."""

    def __init__(
        self,
        settings: Settings | None = None,
        http_client: httpx.Client | None = None,
        aviationstack_client: AviationStackClient | None = None,
    ) -> None:
        self._client = aviationstack_client or AviationStackClient(
            settings=settings,
            http_client=http_client,
        )

    def search_schedules(
        self,
        *,
        origin: str,
        destination: str,
        from_date: str,
        direct_flights: bool = True,
    ) -> list[FlightOption]:
        del direct_flights
        try:
            payload = self._client.get_flights(
                dep_iata=origin,
                arr_iata=destination,
                flight_date=from_date,
            )
        except AviationStackApiError as exc:
            raise FlightApiError(str(exc), code=exc.code) from exc
        return normalize_aviationstack_flights_payload(payload)

    def get_flight_status(
        self,
        *,
        flight_number: str,
        date: str,
    ) -> FlightStatusInfo | None:
        try:
            payload = self._client.get_flights(
                flight_iata=flight_number.replace(" ", "").upper(),
                flight_date=date,
                limit=1,
            )
        except AviationStackApiError as exc:
            raise FlightApiError(str(exc), code=exc.code) from exc
        return normalize_aviationstack_status_payload(payload)


def create_aviationstack_flight_api_client(
    *,
    settings: Settings | None = None,
    http_client: httpx.Client | None = None,
) -> AviationStackFlightApiClient:
    """Build the AviationStack flight provider for dependency injection."""
    return AviationStackFlightApiClient(settings=settings, http_client=http_client)
