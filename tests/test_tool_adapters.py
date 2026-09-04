"""Tool adapter tests — Phase 6.1."""

from app.agent.state import AgentState
from app.agent.workers.booking_worker import BookingWorker
from app.agent.workers.flight_worker import FlightWorker
from app.config import Settings, ToolsMode
from app.mcp.client import InProcessMcpClient
from app.tools.adapters import create_tool_adapter
from app.tools.adapters.direct import DirectToolAdapter
from app.tools.adapters.mcp import McpToolAdapter
from app.tools.booking_service import BookingService
from app.tools.booking_store import BookingStore


def _flight_state() -> AgentState:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.user_message = "Find flights TIA to FRA on 2025-09-15"
    return state


def _direct_adapter(tmp_path) -> DirectToolAdapter:
    store = BookingStore(str(tmp_path / "bookings.db"))
    settings = Settings(flight_api_use_mock=True)
    return DirectToolAdapter(
        settings=settings,
        booking_service=BookingService(store=store, settings=settings),
    )


def test_create_tool_adapter_returns_direct_by_default() -> None:
    adapter = create_tool_adapter(Settings(tools_mode=ToolsMode.DIRECT))

    assert isinstance(adapter, DirectToolAdapter)
    assert adapter.mode == ToolsMode.DIRECT


def test_create_tool_adapter_returns_mcp_when_configured() -> None:
    adapter = create_tool_adapter(Settings(tools_mode=ToolsMode.MCP))

    assert isinstance(adapter, McpToolAdapter)
    assert adapter.mode == ToolsMode.MCP


def test_direct_adapter_runs_search_and_booking(tmp_path) -> None:
    adapter = _direct_adapter(tmp_path)
    state = _flight_state()

    search = adapter.search_flights(state)
    validate = adapter.validate_options(state)
    state.user_message = "Book flight for Ana Krasniqi"
    booking = adapter.create_booking(state)

    assert search.success is True
    assert validate.success is True
    assert booking.success is True
    assert len(state.flight_search.results) == 3
    assert state.booking.booking_id is not None


def test_mcp_adapter_runs_same_actions_via_client(tmp_path) -> None:
    direct = _direct_adapter(tmp_path)
    adapter = McpToolAdapter(
        settings=Settings(tools_mode=ToolsMode.MCP),
        mcp_client=InProcessMcpClient(direct_adapter=direct),
    )
    state = _flight_state()

    search = adapter.search_flights(state)
    validate = adapter.validate_options(state)
    state.user_message = "Book flight for Ana Krasniqi"
    booking = adapter.create_booking(state)

    assert search.success is True
    assert validate.success is True
    assert booking.success is True
    assert adapter.mode == ToolsMode.MCP
    assert state.flight_search.selected_option_id == "LH001"


def test_flight_worker_works_with_direct_and_mcp_adapters(tmp_path) -> None:
    direct = _direct_adapter(tmp_path)
    mcp = McpToolAdapter(
        settings=Settings(tools_mode=ToolsMode.MCP),
        mcp_client=InProcessMcpClient(direct_adapter=direct),
    )

    for adapter in (direct, mcp):
        worker = FlightWorker(adapter=adapter)
        state = _flight_state()

        search = worker.execute("search_flights", state)
        validate = worker.execute("validate_options", state)

        assert search.success is True
        assert validate.success is True
        assert state.flight_search.selected_option_id == "LH001"


def test_booking_worker_works_with_direct_and_mcp_adapters(tmp_path) -> None:
    direct = _direct_adapter(tmp_path)
    mcp = McpToolAdapter(
        settings=Settings(tools_mode=ToolsMode.MCP),
        mcp_client=InProcessMcpClient(direct_adapter=direct),
    )

    for adapter in (direct, mcp):
        worker = BookingWorker(adapter=adapter)
        state = _flight_state()
        state.flight_search.selected_option_id = "LH001"
        state.user_message = "Book flight for Ana Krasniqi"

        result = worker.execute("create_booking", state)

        assert result.success is True
        assert state.booking.booking_id is not None
