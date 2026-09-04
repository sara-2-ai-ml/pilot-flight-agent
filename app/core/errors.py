"""Application error types and graceful error handling."""

from __future__ import annotations

from enum import Enum

from app.core.circuit_breaker import CircuitBreakerOpenError
from app.core.timeout import ExternalCallTimeoutError
from app.mcp.result_parsing import McpClientError
from app.tools.booking_store import BookingStoreError
from app.tools.flight_client import FlightApiError

DEFAULT_USER_ERROR_MESSAGE = (
    "Something went wrong while processing your request. Please try again."
)

CIRCUIT_OPEN_USER_MESSAGE = (
    "Flight search is temporarily unavailable due to repeated failures. "
    "Please try again later."
)


class ErrorCode(str, Enum):
    """Stable error codes for worker and evaluator handling."""

    FLIGHT_UNAVAILABLE = "flight_unavailable"
    BOOKING_UNAVAILABLE = "booking_unavailable"
    EXTERNAL_TIMEOUT = "external_timeout"
    CIRCUIT_OPEN = "circuit_open"
    MCP_UNAVAILABLE = "mcp_unavailable"
    VALIDATION = "validation"
    MISSING_ROUTE = "missing_route"
    MISSING_DATE = "missing_date"
    NEEDS_CLARIFICATION = "needs_clarification"
    UNEXPECTED = "unexpected"


EVALUATOR_FAIL_ERROR_CODES = frozenset({ErrorCode.CIRCUIT_OPEN.value})

ASK_USER_ERROR_CODES = frozenset(
    {
        ErrorCode.VALIDATION.value,
        ErrorCode.MISSING_ROUTE.value,
        ErrorCode.MISSING_DATE.value,
        ErrorCode.NEEDS_CLARIFICATION.value,
    }
)


def is_clarification_error(error_code: str | None) -> bool:
    """Return True when a worker failure should ask the user for more input."""
    return error_code in ASK_USER_ERROR_CODES


def is_terminal_worker_failure(error_code: str | None) -> bool:
    """Return True when a worker failure should stop the plan immediately."""
    return error_code in EVALUATOR_FAIL_ERROR_CODES


class GracefulError(Exception):
    """Controlled failure with a safe user-facing message."""

    def __init__(
        self,
        *,
        user_message: str,
        code: ErrorCode | str,
        retryable: bool = False,
    ) -> None:
        self.user_message = user_message
        self.code = code.value if isinstance(code, ErrorCode) else code
        self.retryable = retryable
        super().__init__(user_message)


class FlightUnavailableError(GracefulError):
    """Flight provider could not fulfill a request."""

    def __init__(
        self,
        *,
        user_message: str,
        retryable: bool = True,
    ) -> None:
        super().__init__(
            user_message=user_message,
            code=ErrorCode.FLIGHT_UNAVAILABLE,
            retryable=retryable,
        )


class BookingUnavailableError(GracefulError):
    """Booking store or booking workflow could not complete."""

    def __init__(
        self,
        *,
        user_message: str = "I couldn't complete the booking right now. Please try again later.",
        retryable: bool = True,
    ) -> None:
        super().__init__(
            user_message=user_message,
            code=ErrorCode.BOOKING_UNAVAILABLE,
            retryable=retryable,
        )


class AgentFailure(Exception):
    """Controlled agent failure with a safe user-facing message."""

    def __init__(
        self,
        *,
        message: str,
        trace_id: str,
        issue: str | None = None,
    ) -> None:
        self.message = message
        self.trace_id = trace_id
        self.issue = issue
        super().__init__(message)


def graceful_error_from_exception(exc: BaseException) -> GracefulError:
    """Map an internal exception to a safe GracefulError."""
    if isinstance(exc, GracefulError):
        return exc

    if isinstance(exc, FlightApiError):
        if exc.code == ErrorCode.CIRCUIT_OPEN.value:
            return GracefulError(
                user_message=CIRCUIT_OPEN_USER_MESSAGE,
                code=ErrorCode.CIRCUIT_OPEN,
                retryable=False,
            )
        return FlightUnavailableError(
            user_message=(
                "I couldn't retrieve live flight data right now. Please try again later."
            ),
        )

    if isinstance(exc, CircuitBreakerOpenError):
        return GracefulError(
            user_message=CIRCUIT_OPEN_USER_MESSAGE,
            code=ErrorCode.CIRCUIT_OPEN,
            retryable=False,
        )

    if isinstance(exc, ExternalCallTimeoutError):
        return GracefulError(
            user_message="The request took too long to complete. Please try again later.",
            code=ErrorCode.EXTERNAL_TIMEOUT,
            retryable=True,
        )

    if isinstance(exc, McpClientError):
        return GracefulError(
            user_message="A tool request failed. Please try again later.",
            code=ErrorCode.MCP_UNAVAILABLE,
            retryable=True,
        )

    if isinstance(exc, BookingStoreError):
        return BookingUnavailableError()

    return GracefulError(
        user_message=DEFAULT_USER_ERROR_MESSAGE,
        code=ErrorCode.UNEXPECTED,
        retryable=False,
    )


def to_worker_failure(error: GracefulError) -> "WorkerResult":
    """Convert a GracefulError into a failed worker result."""
    from app.agent.workers.base import WorkerResult

    return WorkerResult(
        message=error.user_message,
        success=False,
        error_code=error.code,
        retryable=error.retryable,
    )
