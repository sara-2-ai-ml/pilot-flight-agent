"""Flight worker — search, validate, normalize flight data."""

from app.agent.state import AgentState
from app.agent.workers.base import BaseWorker, WorkerResult
from app.models.planning import Worker
from app.tools.adapters import create_tool_adapter
from app.tools.adapters.base import ToolAdapter


class FlightWorker(BaseWorker):
    """Handles flight-domain plan steps."""

    def __init__(self, adapter: ToolAdapter | None = None) -> None:
        self._adapter: ToolAdapter = adapter or create_tool_adapter()

    @property
    def worker_type(self) -> Worker:
        return Worker.FLIGHT

    @property
    def supported_actions(self) -> frozenset[str]:
        return frozenset({"search_flights", "validate_options"})

    def _run(self, action: str, state: AgentState) -> WorkerResult:
        if action == "search_flights":
            return self._adapter.search_flights(state)
        return self._adapter.validate_options(state)
