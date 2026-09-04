"""External call timeout tests — Phase 9.2."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import httpx
import pytest

from app.agent.planning import LlmPlanner, PlanningError
from app.agent.state import AgentState
from app.config import Settings
from app.core.timeout import ExternalCallTimeoutError, await_with_timeout, run_with_timeout
from app.mcp.stdio_transport import list_mcp_tools
from app.tools.lufthansa_client import LufthansaAccessToken, LufthansaApiError, LufthansaClient


@pytest.mark.asyncio
async def test_await_with_timeout_returns_result_when_fast() -> None:
    async def fast() -> str:
        return "ok"

    result = await await_with_timeout(
        fast(),
        timeout_seconds=1.0,
        operation="fast call",
    )

    assert result == "ok"


@pytest.mark.asyncio
async def test_await_with_timeout_raises_when_slow() -> None:
    async def slow() -> str:
        await asyncio.sleep(0.05)
        return "late"

    with pytest.raises(ExternalCallTimeoutError, match="slow call timed out"):
        await await_with_timeout(
            slow(),
            timeout_seconds=0.01,
            operation="slow call",
        )


def test_run_with_timeout_raises_from_sync_code() -> None:
    async def slow() -> str:
        await asyncio.sleep(0.05)
        return "late"

    with pytest.raises(ExternalCallTimeoutError, match="sync call timed out"):
        run_with_timeout(
            slow(),
            timeout_seconds=0.01,
            operation="sync call",
        )


def test_lufthansa_client_fails_when_request_hangs() -> None:
    client = LufthansaClient(
        settings=Settings(
            flight_api_key="id",
            flight_api_client_secret="secret",
            retry_enabled=False,
            external_http_timeout_seconds=0.05,
        ),
        http_client=httpx.Client(base_url="https://api.lufthansa.com/v1"),
    )
    client._cached_token = LufthansaAccessToken(access_token="test-token", expires_in=3600)

    def _raise_timeout(*_args: object, **_kwargs: object) -> httpx.Response:
        raise httpx.ReadTimeout("The read operation timed out")

    client._http.request = _raise_timeout  # type: ignore[method-assign]

    with pytest.raises(LufthansaApiError, match="timed out"):
        client.get_schedules(origin="TIA", destination="FRA", from_date="2025-09-15")


def test_llm_planner_raises_planning_error_on_timeout() -> None:
    mock_client = pytest.importorskip("unittest.mock").MagicMock()
    mock_client.messages.create.side_effect = __import__("anthropic").APITimeoutError(
        request=__import__("httpx").Request("POST", "https://api.anthropic.com/v1/messages"),
    )

    planner = LlmPlanner(
        settings=Settings(
            anthropic_api_key="test-key",
            external_llm_timeout_seconds=30.0,
        ),
        client=mock_client,
    )
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.user_message = "Find flights TIA to FRA"

    with pytest.raises(PlanningError, match="LLM planner timed out"):
        planner.create_plan(state)


@pytest.mark.asyncio
async def test_list_mcp_tools_times_out_when_server_hangs() -> None:
    with patch("app.mcp.stdio_transport.stdio_client") as mock_stdio:
        mock_stdio.side_effect = lambda *_args, **_kwargs: _HangingContext()

    with pytest.raises(ExternalCallTimeoutError, match="MCP list_tools"):
        await list_mcp_tools(
            command="python",
            args=["-m", "app.mcp.servers.lufthansa_server"],
            timeout_seconds=0.01,
        )


class _HangingContext:
    async def __aenter__(self) -> tuple[object, object]:
        await asyncio.sleep(0.05)
        return object(), object()

    async def __aexit__(self, *_args: object) -> None:
        return None
