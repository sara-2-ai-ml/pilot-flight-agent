"""Abstract tool adapter contract shared by direct and MCP modes."""

from typing import Protocol, runtime_checkable

from app.agent.state import AgentState
from app.agent.workers.base import WorkerResult
from app.config import ToolsMode


@runtime_checkable
class ToolAdapter(Protocol):
    """Provider-agnostic tool surface used by workers."""

    @property
    def mode(self) -> ToolsMode:
        """Integration mode this adapter implements."""

    def search_flights(self, state: AgentState) -> WorkerResult:
        """Search flights and populate session flight state."""

    def validate_options(self, state: AgentState) -> WorkerResult:
        """Validate and select a flight option in session state."""

    def create_booking(self, state: AgentState) -> WorkerResult:
        """Create a booking and populate session booking state."""
