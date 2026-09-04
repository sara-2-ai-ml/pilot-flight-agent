"""MCP client — tool discovery and invocation."""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING, Any, Protocol

from app.agent.state import AgentState
from app.agent.workers.base import WorkerResult
from app.config import Settings, get_settings
from app.core.errors import graceful_error_from_exception, to_worker_failure
from app.mcp.result_parsing import McpClientError
from app.mcp.stdio_transport import (
    get_mcp_prompt,
    invoke_mcp_tool,
    list_mcp_prompts,
    list_mcp_tools,
    read_mcp_resource,
    run_mcp_coroutine,
)
from app.mcp.worker_bridge import (
    apply_create_booking,
    apply_search_results,
    apply_validate_options,
)
from app.models.flight import FlightOption
from app.tools.flight_client import normalize_travel_date
from app.tools.flight_service import parse_route, parse_travel_date
from app.tools.booking_service import parse_passenger_name

if TYPE_CHECKING:
    from app.tools.adapters.direct import DirectToolAdapter

LUFTHANSA_SERVER_MODULE = "app.mcp.servers.lufthansa_server"
BOOKING_SERVER_MODULE = "app.mcp.servers.booking_server"


class McpClient(Protocol):
    """Minimal MCP client surface used by McpToolAdapter."""

    def call_tool(self, tool_name: str, *, state: AgentState) -> WorkerResult:
        """Invoke one MCP tool and return the worker-facing result."""


class InProcessMcpClient:
    """In-process MCP bridge for tests and local fallback."""

    _TOOL_NAMES = frozenset({"search_flights", "validate_options", "create_booking"})

    def __init__(self, *, direct_adapter: DirectToolAdapter | None = None) -> None:
        from app.tools.adapters.direct import DirectToolAdapter as DirectToolAdapterImpl

        self._direct_adapter = direct_adapter or DirectToolAdapterImpl()

    def call_tool(self, tool_name: str, *, state: AgentState) -> WorkerResult:
        if tool_name not in self._TOOL_NAMES:
            return WorkerResult(
                message=f"Unknown MCP tool '{tool_name}'.",
                success=False,
            )
        if tool_name == "search_flights":
            return self._direct_adapter.search_flights(state)
        if tool_name == "validate_options":
            return self._direct_adapter.validate_options(state)
        return self._direct_adapter.create_booking(state)


class RemoteMcpClient:
    """Call standalone MCP servers over stdio and map results onto session state."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        python_executable: str | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._python = python_executable or self._settings.mcp_python_executable or sys.executable

    def _server_args(self, module: str) -> tuple[str, list[str]]:
        return self._python, ["-m", module]

    def _subprocess_env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["BOOKING_DB_PATH"] = self._settings.booking_db_path
        return env

    def list_tools(self, *, server: str) -> list[str]:
        module = _server_module(server)
        command, args = self._server_args(module)
        return run_mcp_coroutine(
            list_mcp_tools(
                command=command,
                args=args,
                env=self._subprocess_env(),
                timeout_seconds=self._settings.external_mcp_timeout_seconds,
            ),
        )

    def list_prompts(self, *, server: str) -> list[str]:
        module = _server_module(server)
        command, args = self._server_args(module)
        return run_mcp_coroutine(
            list_mcp_prompts(
                command=command,
                args=args,
                env=self._subprocess_env(),
                timeout_seconds=self._settings.external_mcp_timeout_seconds,
            ),
        )

    def get_prompt(
        self,
        *,
        server: str,
        prompt_name: str,
        arguments: dict[str, str] | None = None,
    ) -> str:
        module = _server_module(server)
        command, args = self._server_args(module)
        return run_mcp_coroutine(
            get_mcp_prompt(
                command=command,
                args=args,
                prompt_name=prompt_name,
                arguments=arguments,
                env=self._subprocess_env(),
                timeout_seconds=self._settings.external_mcp_timeout_seconds,
            ),
        )

    def read_resource(self, *, server: str | None = None, uri: str) -> str:
        resolved_server = server or _server_for_uri(uri)
        module = _server_module(resolved_server)
        command, args = self._server_args(module)
        return run_mcp_coroutine(
            read_mcp_resource(
                command=command,
                args=args,
                uri=uri,
                env=self._subprocess_env(),
                timeout_seconds=self._settings.external_mcp_timeout_seconds,
            ),
        )

    def call_tool(self, tool_name: str, *, state: AgentState) -> WorkerResult:
        try:
            if tool_name == "validate_options":
                return apply_validate_options(state)
            if tool_name == "search_flights":
                return self._search_flights(state)
            if tool_name == "create_booking":
                return self._create_booking(state)
        except McpClientError as exc:
            return to_worker_failure(graceful_error_from_exception(exc))
        except Exception as exc:
            return to_worker_failure(graceful_error_from_exception(exc))

        return WorkerResult(
            message=f"Unknown MCP tool '{tool_name}'.",
            success=False,
        )

    def _search_flights(self, state: AgentState) -> WorkerResult:
        origin, destination = parse_route(state.user_message)
        if origin is None or destination is None:
            return WorkerResult(
                message="Please provide origin and destination airport codes (e.g. TIA to FRA).",
                success=False,
            )

        travel_date = parse_travel_date(state.user_message)
        api_date = normalize_travel_date(travel_date)
        command, args = self._server_args(LUFTHANSA_SERVER_MODULE)
        payload = run_mcp_coroutine(
            invoke_mcp_tool(
                command=command,
                args=args,
                tool_name="search_flights",
                arguments={
                    "origin": origin,
                    "destination": destination,
                    "from_date": api_date,
                },
                env=self._subprocess_env(),
                timeout_seconds=self._settings.external_mcp_timeout_seconds,
            ),
        )
        options = _coerce_flight_options(payload)
        source = "mock" if self._settings.flight_api_use_mock else "live"
        return apply_search_results(
            state,
            options,
            origin=origin,
            destination=destination,
            travel_date=travel_date or api_date,
            source=source,
        )

    def _create_booking(self, state: AgentState) -> WorkerResult:
        flight_id = state.flight_search.selected_option_id
        if flight_id is None:
            return WorkerResult(
                message="No validated flight selected. Validate options before booking.",
                success=False,
            )

        command, args = self._server_args(BOOKING_SERVER_MODULE)
        payload = run_mcp_coroutine(
            invoke_mcp_tool(
                command=command,
                args=args,
                tool_name="create_booking",
                arguments={
                    "conversation_id": state.conversation_id,
                    "flight_id": flight_id,
                    "passenger": parse_passenger_name(state.user_message),
                },
                env=self._subprocess_env(),
                timeout_seconds=self._settings.external_mcp_timeout_seconds,
            ),
        )
        if not isinstance(payload, dict):
            raise McpClientError("Booking MCP server returned an unexpected payload.")
        return apply_create_booking(state, payload)


def _server_module(server: str) -> str:
    normalized = server.strip().lower()
    if normalized in {"lufthansa", "flight", "flights"}:
        return LUFTHANSA_SERVER_MODULE
    if normalized in {"booking", "bookings"}:
        return BOOKING_SERVER_MODULE
    raise McpClientError(f"Unknown MCP server '{server}'.")


def _server_for_uri(uri: str) -> str:
    if uri.startswith(("airports://", "airport://")):
        return "lufthansa"
    if uri.startswith("bookings://"):
        return "booking"
    raise McpClientError(f"Unknown MCP resource URI '{uri}'.")


def _coerce_flight_options(payload: Any) -> list[FlightOption]:
    if not isinstance(payload, list):
        raise McpClientError("Flight search MCP tool returned an unexpected payload.")
    return [FlightOption.model_validate(item) for item in payload]


def create_mcp_client(
    *,
    settings: Settings | None = None,
    direct_adapter: DirectToolAdapter | None = None,
) -> McpClient:
    """Build the configured MCP client implementation."""
    resolved = settings or get_settings()
    if resolved.mcp_use_inprocess:
        from app.tools.adapters.direct import DirectToolAdapter as DirectToolAdapterImpl

        return InProcessMcpClient(
            direct_adapter=direct_adapter or DirectToolAdapterImpl(settings=resolved),
        )
    return RemoteMcpClient(settings=resolved)
