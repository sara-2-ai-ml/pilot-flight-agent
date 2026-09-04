"""Lufthansa Open API HTTP client — isolated from workers and coordinator."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
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
    normalize_flight_status_payload,
    normalize_schedule_payload,
)
from app.tools.flight_client import FlightApiError

T = TypeVar("T")

_AUTH_HEADERS = {"Content-Type": "application/x-www-form-urlencoded"}
_JSON_HEADERS = {"Accept": "application/json"}
_RETRYABLE_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})
_LUFTHANSA_CIRCUIT = "lufthansa_api"
_logger = get_logger("tools.lufthansa")


class LufthansaApiError(Exception):
    """Raised when the Lufthansa API returns an error or cannot be reached."""

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


def is_lufthansa_retryable_error(exc: BaseException) -> bool:
    """Return True when a Lufthansa request should be retried."""
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, LufthansaApiError):
        return exc.status_code in _RETRYABLE_STATUS_CODES
    return False


def is_lufthansa_circuit_failure(exc: BaseException) -> bool:
    """Return True when a failure should count toward the circuit breaker."""
    if isinstance(exc, CircuitBreakerOpenError):
        return False
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, LufthansaApiError):
        if exc.status_code is None:
            return True
        return exc.status_code in _RETRYABLE_STATUS_CODES
    return False


@dataclass(frozen=True)
class LufthansaAccessToken:
    access_token: str
    expires_in: int


class LufthansaClient:
    """Thin HTTP wrapper for Lufthansa public operations endpoints."""

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
        self._cached_token: LufthansaAccessToken | None = None

    def close(self) -> None:
        if self._owns_client:
            self._http.close()

    def __enter__(self) -> LufthansaClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _require_credentials(self) -> tuple[str, str]:
        client_id = self._settings.flight_api_key
        client_secret = self._settings.flight_api_client_secret
        if not client_id or not client_secret:
            raise LufthansaApiError("Flight API credentials are not configured.")
        return client_id, client_secret

    def _call_with_retry(self, operation: Callable[[], T]) -> T:
        policy = RetryPolicy.from_settings(self._settings)

        def _on_retry(attempt: int, exc: BaseException, delay: float) -> None:
            _logger.warning(
                "lufthansa_request_retry",
                extra={
                    "event": "lufthansa_request_retry",
                    "attempt": attempt,
                    "delay_seconds": delay,
                    "error": str(exc),
                },
            )

        try:
            return retry_with_backoff(
                operation,
                policy=policy,
                is_retryable=is_lufthansa_retryable_error,
                on_retry=_on_retry,
            )
        except RetryExhaustedError as exc:
            if exc.last_error is not None:
                raise exc.last_error from exc
            raise LufthansaApiError("Lufthansa API request failed after retries.") from exc

    def _call_with_reliability(self, operation: Callable[[], T]) -> T:
        breaker = get_circuit_breaker()
        breaker_policy = CircuitBreakerPolicy.from_settings(self._settings)

        try:
            breaker.allow(_LUFTHANSA_CIRCUIT, breaker_policy)
        except CircuitBreakerOpenError as exc:
            _logger.warning(
                "lufthansa_circuit_open",
                extra={
                    "event": "lufthansa_circuit_open",
                    "circuit": exc.circuit,
                    "retry_after_seconds": exc.retry_after_seconds,
                },
            )
            raise LufthansaApiError(
                "Flight API circuit breaker is open; failing fast.",
                code=ErrorCode.CIRCUIT_OPEN.value,
            ) from exc

        try:
            result = self._call_with_retry(operation)
        except BaseException as exc:
            if is_lufthansa_circuit_failure(exc):
                breaker.record_failure(_LUFTHANSA_CIRCUIT, breaker_policy)
            raise

        breaker.record_success(_LUFTHANSA_CIRCUIT)
        return result

    def fetch_access_token(self, *, force_refresh: bool = False) -> LufthansaAccessToken:
        """Exchange API key + secret for a short-lived bearer token."""
        if self._cached_token is not None and not force_refresh:
            return self._cached_token

        client_id, client_secret = self._require_credentials()

        def _fetch() -> LufthansaAccessToken:
            try:
                response = self._http.post(
                    "/oauth/token",
                    headers=_AUTH_HEADERS,
                    data={
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "grant_type": "client_credentials",
                    },
                )
            except httpx.TimeoutException as exc:
                raise LufthansaApiError(
                    "Timed out obtaining Lufthansa access token "
                    f"after {self._settings.external_http_timeout_seconds} seconds.",
                ) from exc

            if response.status_code >= 400:
                raise LufthansaApiError(
                    "Failed to obtain Lufthansa access token.",
                    status_code=response.status_code,
                )

            payload = response.json()
            return LufthansaAccessToken(
                access_token=payload["access_token"],
                expires_in=int(payload.get("expires_in", 0)),
            )

        token = self._call_with_reliability(_fetch)
        self._cached_token = token
        return token

    def _authorized_headers(self) -> dict[str, str]:
        token = self.fetch_access_token()
        return {
            **_JSON_HEADERS,
            "Authorization": f"Bearer {token.access_token}",
        }

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        def _request() -> dict[str, Any]:
            try:
                response = self._http.request(
                    method,
                    path,
                    headers=self._authorized_headers(),
                    params=params,
                )
            except httpx.TimeoutException as exc:
                raise LufthansaApiError(
                    f"Lufthansa API request timed out for {path} "
                    f"after {self._settings.external_http_timeout_seconds} seconds.",
                ) from exc

            if response.status_code >= 400:
                raise LufthansaApiError(
                    f"Lufthansa API request failed for {path}.",
                    status_code=response.status_code,
                )
            payload = response.json()
            if not isinstance(payload, dict):
                raise LufthansaApiError(f"Lufthansa API returned unexpected payload for {path}.")
            return payload

        return self._call_with_reliability(_request)

    def get_schedules(
        self,
        *,
        origin: str,
        destination: str,
        from_date: str,
        direct_flights: bool = False,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Fetch scheduled flights between two airports on a given date."""
        path = f"/operations/schedules/{origin.upper()}/{destination.upper()}/{from_date}"
        return self._request_json(
            "GET",
            path,
            params={
                "directFlights": str(direct_flights).lower(),
                "limit": limit,
                "offset": offset,
            },
        )

    def get_flight_status(
        self,
        *,
        flight_number: str,
        date: str,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Fetch operational status for one flight number on a given date."""
        path = f"/operations/flightstatus/{flight_number.upper()}/{date}"
        return self._request_json(
            "GET",
            path,
            params={"limit": limit, "offset": offset},
        )


def create_lufthansa_client(
    *,
    settings: Settings | None = None,
    http_client: httpx.Client | None = None,
) -> LufthansaClient:
    """Build a client instance for dependency injection in tests and services."""
    return LufthansaClient(settings=settings, http_client=http_client)


class LufthansaFlightApiClient:
    """Lufthansa-backed FlightApiClient — the only file that knows API paths and auth."""

    def __init__(
        self,
        settings: Settings | None = None,
        http_client: httpx.Client | None = None,
        lufthansa_client: LufthansaClient | None = None,
    ) -> None:
        self._client = lufthansa_client or LufthansaClient(
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
        try:
            payload = self._client.get_schedules(
                origin=origin,
                destination=destination,
                from_date=from_date,
                direct_flights=direct_flights,
            )
        except LufthansaApiError as exc:
            raise FlightApiError(str(exc), code=exc.code) from exc
        return normalize_schedule_payload(payload)

    def get_flight_status(
        self,
        *,
        flight_number: str,
        date: str,
    ) -> FlightStatusInfo | None:
        try:
            payload = self._client.get_flight_status(
                flight_number=flight_number.replace(" ", "").upper(),
                date=date,
            )
        except LufthansaApiError as exc:
            raise FlightApiError(str(exc), code=exc.code) from exc
        return normalize_flight_status_payload(payload)


def create_lufthansa_flight_api_client(
    *,
    settings: Settings | None = None,
    http_client: httpx.Client | None = None,
) -> LufthansaFlightApiClient:
    """Build the Lufthansa flight provider for dependency injection."""
    return LufthansaFlightApiClient(settings=settings, http_client=http_client)
