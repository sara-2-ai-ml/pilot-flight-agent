"""Specialized workers — flight search and booking."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.agent.workers.base import BaseWorker, WorkerResult
from app.config import Settings, get_settings
from app.models.planning import Worker

if TYPE_CHECKING:
    from app.tools.adapters.base import ToolAdapter


class WorkerRegistry:
    """Maps planning worker enums to concrete worker implementations."""

    def __init__(
        self,
        *,
        flight_worker: BaseWorker | None = None,
        booking_worker: BaseWorker | None = None,
        tool_adapter: ToolAdapter | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._flight_worker = flight_worker
        self._booking_worker = booking_worker
        self._tool_adapter = tool_adapter
        self._settings = settings

    def _resolve_adapter(self) -> ToolAdapter:
        from app.tools.adapters import create_tool_adapter

        if self._tool_adapter is None:
            self._tool_adapter = create_tool_adapter(self._settings or get_settings())
        return self._tool_adapter

    def get(self, worker: Worker) -> BaseWorker:
        if worker == Worker.FLIGHT:
            if self._flight_worker is None:
                from app.agent.workers.flight_worker import FlightWorker

                self._flight_worker = FlightWorker(adapter=self._resolve_adapter())
            return self._flight_worker
        if worker == Worker.BOOKING:
            if self._booking_worker is None:
                from app.agent.workers.booking_worker import BookingWorker

                self._booking_worker = BookingWorker(adapter=self._resolve_adapter())
            return self._booking_worker
        raise ValueError(f"Unknown worker: {worker}")


def configure_worker_registry(settings: Settings | None = None) -> WorkerRegistry:
    """Bind the app-wide worker registry to the active tool runtime settings."""
    global _default_registry

    from app.tools.adapters import clear_tool_adapter_cache

    resolved = settings or get_settings()
    _default_registry = WorkerRegistry(settings=resolved)
    clear_tool_adapter_cache()
    return _default_registry


def reset_worker_registry() -> None:
    """Reset the app-wide worker registry — for tests."""
    configure_worker_registry(Settings())


_default_registry = WorkerRegistry()


def get_worker(worker: Worker) -> BaseWorker:
    """Return the worker implementation for a plan step."""
    return _default_registry.get(worker)


def get_worker_registry() -> WorkerRegistry:
    """Return the app-wide worker registry."""
    return _default_registry
