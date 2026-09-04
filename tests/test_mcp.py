"""MCP client ↔ server integration tests — Phase 11.5."""

import pytest

from app.agent.state import AgentState
from app.config import Settings
from app.mcp.client import InProcessMcpClient, RemoteMcpClient, create_mcp_client
from app.mcp.stdio_transport import invoke_mcp_tool, run_mcp_coroutine
from app.models.booking import BookingStatus
from app.tools.adapters.direct import DirectToolAdapter
from app.tools.adapters.mcp import McpToolAdapter
from app.tools.booking_service import BookingService
from app.tools.booking_store import BookingStore


def _remote_client(tmp_path, **settings_overrides) -> RemoteMcpClient:
    db_path = tmp_path / "bookings.db"
    settings = Settings(
        flight_api_use_mock=True,
        booking_db_path=str(db_path),
        mcp_use_inprocess=False,
        **settings_overrides,
    )
    return RemoteMcpClient(settings=settings)


def _subprocess_env(client: RemoteMcpClient) -> dict[str, str]:
    return client._subprocess_env()


@pytest.mark.asyncio
async def test_stdio_client_lists_tools_from_lufthansa_server() -> None:
    client = RemoteMcpClient(settings=Settings(flight_api_use_mock=True))
    command, args = client._server_args("app.mcp.servers.lufthansa_server")

    from app.mcp.stdio_transport import list_mcp_tools

    tools = await list_mcp_tools(
        command=command,
        args=args,
        env=_subprocess_env(client),
        timeout_seconds=15.0,
    )

    assert tools == ["search_flights", "get_flight_status"]


@pytest.mark.asyncio
async def test_stdio_client_lists_tools_from_booking_server(tmp_path) -> None:
    client = _remote_client(tmp_path)
    command, args = client._server_args("app.mcp.servers.booking_server")

    from app.mcp.stdio_transport import list_mcp_tools

    tools = await list_mcp_tools(
        command=command,
        args=args,
        env=_subprocess_env(client),
        timeout_seconds=15.0,
    )

    assert tools == ["create_booking", "get_booking", "cancel_booking"]


def test_remote_client_discovers_tools_on_both_servers(tmp_path) -> None:
    client = _remote_client(tmp_path)

    lufthansa_tools = client.list_tools(server="lufthansa")
    booking_tools = client.list_tools(server="booking")

    assert lufthansa_tools == ["search_flights", "get_flight_status"]
    assert booking_tools == ["create_booking", "get_booking", "cancel_booking"]


def test_remote_client_search_flights_reaches_lufthansa_server(tmp_path) -> None:
    client = _remote_client(tmp_path)
    command, args = client._server_args("app.mcp.servers.lufthansa_server")

    payload = run_mcp_coroutine(
        invoke_mcp_tool(
            command=command,
            args=args,
            tool_name="search_flights",
            arguments={
                "origin": "TIA",
                "destination": "FRA",
                "from_date": "2025-09-15",
            },
            env=_subprocess_env(client),
            timeout_seconds=15.0,
        ),
    )

    assert isinstance(payload, list)
    assert len(payload) == 3
    assert payload[0]["id"] == "LH001"
    assert payload[0]["origin"] == "TIA"


def test_remote_client_create_booking_reaches_booking_server(tmp_path) -> None:
    client = _remote_client(tmp_path)
    command, args = client._server_args("app.mcp.servers.booking_server")

    payload = run_mcp_coroutine(
        invoke_mcp_tool(
            command=command,
            args=args,
            tool_name="create_booking",
            arguments={
                "conversation_id": "conv-mcp",
                "flight_id": "LH001",
                "passenger": "Ana Krasniqi",
            },
            env=_subprocess_env(client),
            timeout_seconds=15.0,
        ),
    )

    assert payload["found"] is True
    assert payload["booking_id"].startswith("BK-")
    assert payload["status"] == BookingStatus.PENDING.value
    assert BookingStore(str(tmp_path / "bookings.db")).get(payload["booking_id"]) is not None


def test_remote_client_reads_resources_from_both_servers(tmp_path) -> None:
    client = _remote_client(tmp_path)

    airport = client.read_resource(server="lufthansa", uri="airports://TIA")
    help_text = client.read_resource(server="booking", uri="bookings://help")

    assert "Tirana" in airport
    assert "create_booking" in help_text


def test_remote_client_call_tool_runs_search_validate_book_flow(tmp_path) -> None:
    client = _remote_client(tmp_path)
    state = AgentState.new(conversation_id="conv-mcp-flow", trace_id="trace-mcp-flow")
    state.user_message = "Find flights TIA to FRA on 2025-09-15"

    search = client.call_tool("search_flights", state=state)
    validate = client.call_tool("validate_options", state=state)
    state.user_message = "Book flight for Ana Krasniqi"
    booking = client.call_tool("create_booking", state=state)

    assert search.success is True
    assert "Found 3 mock flights from TIA to FRA" in search.message
    assert validate.success is True
    assert booking.success is True
    assert state.booking.booking_id is not None
    assert BookingStore(str(tmp_path / "bookings.db")).get(state.booking.booking_id) is not None


def test_mcp_tool_adapter_uses_remote_client_against_servers(tmp_path) -> None:
    db_path = tmp_path / "bookings.db"
    settings = Settings(
        flight_api_use_mock=True,
        booking_db_path=str(db_path),
        mcp_use_inprocess=False,
    )
    adapter = McpToolAdapter(
        settings=settings,
        mcp_client=RemoteMcpClient(settings=settings),
    )
    state = AgentState.new(conversation_id="conv-adapter", trace_id="trace-adapter")
    state.user_message = "Find flights TIA to FRA on 2025-09-15"

    search = adapter.search_flights(state)
    validate = adapter.validate_options(state)

    assert search.success is True
    assert validate.success is True
    assert len(state.flight_search.results) == 3


def test_inprocess_and_remote_clients_both_search_flights(tmp_path) -> None:
    db_path = str(tmp_path / "bookings.db")
    store = BookingStore(db_path)
    settings = Settings(flight_api_use_mock=True, booking_db_path=db_path)
    direct = DirectToolAdapter(
        settings=settings,
        booking_service=BookingService(store=store, settings=settings),
    )
    inprocess = InProcessMcpClient(direct_adapter=direct)
    remote = _remote_client(tmp_path)

    inprocess_state = AgentState.new(conversation_id="conv-in", trace_id="trace-in")
    inprocess_state.user_message = "Find flights TIA to FRA on 2025-09-15"
    remote_state = AgentState.new(conversation_id="conv-remote", trace_id="trace-remote")
    remote_state.user_message = "Find flights TIA to FRA on 2025-09-15"

    inprocess_result = inprocess.call_tool("search_flights", state=inprocess_state)
    remote_result = remote.call_tool("search_flights", state=remote_state)

    assert inprocess_result.success is True
    assert remote_result.success is True
    assert len(inprocess_state.flight_search.results) == 3
    assert len(remote_state.flight_search.results) == 3


def test_create_mcp_client_selects_remote_for_stdio_integration(tmp_path) -> None:
    settings = Settings(
        flight_api_use_mock=True,
        booking_db_path=str(tmp_path / "bookings.db"),
        mcp_use_inprocess=False,
    )

    client = create_mcp_client(settings=settings)

    assert isinstance(client, RemoteMcpClient)
    assert client.list_tools(server="lufthansa") == ["search_flights", "get_flight_status"]
