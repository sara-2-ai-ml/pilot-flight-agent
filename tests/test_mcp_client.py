"""MCP client tests — Phase 6.4."""

import json

import pytest

from app.agent.state import AgentState
from app.config import Settings
from app.mcp.client import InProcessMcpClient, RemoteMcpClient, create_mcp_client
from app.mcp.result_parsing import extract_tool_result
from app.tools.adapters.direct import DirectToolAdapter
from app.tools.adapters.mcp import McpToolAdapter
from app.tools.booking_service import BookingService
from app.tools.booking_store import BookingStore


class _FakeContent:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeResult:
    def __init__(self, *, structured: dict | None = None, texts: list[str] | None = None) -> None:
        self.structuredContent = structured
        self.content = [_FakeContent(text) for text in (texts or [])]
        self.isError = False


def test_extract_tool_result_prefers_structured_content() -> None:
    payload = extract_tool_result(
        _FakeResult(structured={"result": [{"id": "LH001"}]}),
    )

    assert payload == [{"id": "LH001"}]


def test_extract_tool_result_parses_text_json() -> None:
    payload = extract_tool_result(
        _FakeResult(texts=[json.dumps({"found": True, "booking_id": "BK-1"})]),
    )

    assert payload == {"found": True, "booking_id": "BK-1"}


def test_create_mcp_client_returns_remote_client_by_default() -> None:
    client = create_mcp_client(settings=Settings(mcp_use_inprocess=False))

    assert isinstance(client, RemoteMcpClient)


def test_create_mcp_client_returns_inprocess_when_configured() -> None:
    client = create_mcp_client(settings=Settings(mcp_use_inprocess=True))

    assert isinstance(client, InProcessMcpClient)


def test_remote_mcp_client_lists_tools_from_lufthansa_server() -> None:
    client = RemoteMcpClient(settings=Settings(flight_api_use_mock=True))

    tools = client.list_tools(server="lufthansa")

    assert tools == ["search_flights", "get_flight_status"]


def test_remote_mcp_client_reads_airport_resource() -> None:
    client = RemoteMcpClient(settings=Settings(flight_api_use_mock=True))

    payload = client.read_resource(server="lufthansa", uri="airports://TIA")

    assert "Tirana" in payload


def test_remote_mcp_client_runs_worker_search_flow(tmp_path) -> None:
    db_path = tmp_path / "bookings.db"
    settings = Settings(
        flight_api_use_mock=True,
        booking_db_path=str(db_path),
        mcp_use_inprocess=False,
    )
    client = RemoteMcpClient(settings=settings)
    adapter = McpToolAdapter(settings=settings, mcp_client=client)
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.user_message = "Find flights TIA to FRA on 2025-09-15"

    search = adapter.search_flights(state)
    validate = adapter.validate_options(state)
    state.user_message = "Book flight for Ana Krasniqi"
    booking = adapter.create_booking(state)

    assert search.success is True
    assert validate.success is True
    assert booking.success is True
    assert len(state.flight_search.results) == 3
    assert state.booking.booking_id is not None
    assert BookingStore(str(db_path)).get(state.booking.booking_id) is not None


def test_inprocess_client_still_available_for_tests(tmp_path) -> None:
    store = BookingStore(str(tmp_path / "bookings.db"))
    settings = Settings(flight_api_use_mock=True)
    direct = DirectToolAdapter(
        settings=settings,
        booking_service=BookingService(store=store, settings=settings),
    )
    client = InProcessMcpClient(direct_adapter=direct)
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.user_message = "Find flights TIA to FRA on 2025-09-15"

    result = client.call_tool("search_flights", state=state)

    assert result.success is True
    assert len(state.flight_search.results) == 3
