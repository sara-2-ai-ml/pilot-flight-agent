"""Booking worker — create booking, validate, audit."""

from app.agent.state import AgentState
from app.agent.workers.base import BaseWorker, WorkerResult
from app.models.planning import Worker
from app.tools.adapters import create_tool_adapter
from app.tools.adapters.base import ToolAdapter


class BookingWorker(BaseWorker):
    """Handles booking-domain plan steps."""

    def __init__(self, adapter: ToolAdapter | None = None) -> None:
        self._adapter: ToolAdapter = adapter or create_tool_adapter()

    @property
    def worker_type(self) -> Worker:
        return Worker.BOOKING

    @property
    def supported_actions(self) -> frozenset[str]:
        return frozenset({"create_booking"})

    def _run(self, action: str, state: AgentState) -> WorkerResult:
        return self._adapter.create_booking(state)
