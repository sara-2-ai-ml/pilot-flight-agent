"""Worker contracts and shared result type."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.agent.state import AgentState
from app.core.errors import GracefulError, graceful_error_from_exception, to_worker_failure
from app.core.logging import get_logger
from app.core.tracing import trace_span
from app.models.planning import Worker

_logger = get_logger("agent.workers")


@dataclass(frozen=True)
class WorkerResult:
    """Outcome of one worker action execution."""

    message: str
    success: bool
    error_code: str | None = None
    retryable: bool = False


class BaseWorker(ABC):
    """Shared contract for all plan step workers."""

    @property
    @abstractmethod
    def worker_type(self) -> Worker:
        """Planning worker enum value this implementation handles."""

    @property
    @abstractmethod
    def supported_actions(self) -> frozenset[str]:
        """Actions this worker can execute."""

    def execute(self, action: str, state: AgentState) -> WorkerResult:
        """Validate the action and delegate to the worker implementation."""
        if action not in self.supported_actions:
            return WorkerResult(
                message=(
                    f"{self.worker_type.value} worker does not support action '{action}'."
                ),
                success=False,
                error_code="unsupported_action",
            )
        with trace_span(
            f"tool:{action}",
            kind="tool",
            worker=self.worker_type.value,
            action=action,
        ) as span:
            try:
                result = self._run(action, state)
            except GracefulError as exc:
                span.mark_error()
                _logger.warning(
                    "worker_graceful_failure",
                    extra={
                        "event": "worker_graceful_failure",
                        "worker": self.worker_type.value,
                        "action": action,
                        "error_code": exc.code,
                    },
                )
                return to_worker_failure(exc)
            except Exception as exc:
                span.mark_error()
                graceful = graceful_error_from_exception(exc)
                _logger.warning(
                    "worker_graceful_failure",
                    extra={
                        "event": "worker_graceful_failure",
                        "worker": self.worker_type.value,
                        "action": action,
                        "error_code": graceful.code,
                        "internal_error": str(exc),
                    },
                )
                return to_worker_failure(graceful)
            if not result.success:
                span.mark_error()
            return result

    @abstractmethod
    def _run(self, action: str, state: AgentState) -> WorkerResult:
        """Execute a supported action."""
