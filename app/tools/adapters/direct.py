"""Direct tool adapter — calls in-process flight and booking services."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.agent.state import AgentState
from app.agent.workers.base import WorkerResult
from app.config import Settings, ToolsMode, get_settings

if TYPE_CHECKING:
    from app.tools.booking_service import BookingService
    from app.tools.flight_service import FlightSearchService


class DirectToolAdapter:
    """Invoke tools through local Python services."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        flight_service: FlightSearchService | None = None,
        booking_service: BookingService | None = None,
    ) -> None:
        from app.tools.booking_service import BookingService as BookingServiceImpl
        from app.tools.flight_service import FlightSearchService as FlightSearchServiceImpl

        self._settings = settings or get_settings()
        self._flight_service = flight_service or FlightSearchServiceImpl(settings=self._settings)
        self._booking_service = booking_service or BookingServiceImpl(settings=self._settings)

    @property
    def mode(self) -> ToolsMode:
        return ToolsMode.DIRECT

    def search_flights(self, state: AgentState) -> WorkerResult:
        return self._flight_service.search_flights(state)

    def validate_options(self, state: AgentState) -> WorkerResult:
        return self._flight_service.validate_options(state)

    def create_booking(self, state: AgentState) -> WorkerResult:
        return self._booking_service.create_booking(state)
