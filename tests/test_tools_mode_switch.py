"""Tools mode switch tests — Phase 6.5."""

import ast
from pathlib import Path

import pytest

from app.agent.loop import run_chat
from app.agent.state import InMemoryStateStore
from app.agent.workers import configure_worker_registry, get_worker
from app.config import Settings, ToolsMode
from app.models.planning import PlanStatus, Worker
from app.tools.adapters.direct import DirectToolAdapter
from app.tools.adapters.mcp import McpToolAdapter
from app.tools.adapters import create_tool_adapter


def test_create_tool_adapter_switches_on_tools_mode() -> None:
    direct = create_tool_adapter(Settings(tools_mode=ToolsMode.DIRECT))
    mcp = create_tool_adapter(
        Settings(tools_mode=ToolsMode.MCP, mcp_use_inprocess=True),
    )

    assert isinstance(direct, DirectToolAdapter)
    assert isinstance(mcp, McpToolAdapter)


def test_configure_worker_registry_binds_adapter_mode() -> None:
    configure_worker_registry(Settings(tools_mode=ToolsMode.DIRECT))
    direct_worker = get_worker(Worker.FLIGHT)
    assert direct_worker._adapter.mode == ToolsMode.DIRECT

    configure_worker_registry(
        Settings(tools_mode=ToolsMode.MCP, mcp_use_inprocess=True),
    )
    mcp_worker = get_worker(Worker.FLIGHT)
    assert mcp_worker._adapter.mode == ToolsMode.MCP


def test_run_chat_completes_plan_in_direct_mode() -> None:
    store = InMemoryStateStore()
    settings = Settings(tools_mode=ToolsMode.DIRECT, flight_api_use_mock=True)

    state, message = run_chat(
        user_message="Book flights TIA to FRA on 2025-09-15",
        trace_id="trace-direct",
        conversation_id="conv-direct",
        settings=settings,
        store=store,
    )

    assert state.plan.status == PlanStatus.IN_PROGRESS
    assert "Found 3 mock flights from TIA to FRA" in message
    assert len(state.flight_search.results) == 3
    assert state.pending_approval is not None
    assert state.pending_approval["flight"]["id"] == "LH001"


def test_run_chat_completes_plan_in_mcp_mode_with_inprocess_client() -> None:
    store = InMemoryStateStore()
    settings = Settings(
        tools_mode=ToolsMode.MCP,
        flight_api_use_mock=True,
        mcp_use_inprocess=True,
    )

    state, message = run_chat(
        user_message="Book flights TIA to FRA on 2025-09-15",
        trace_id="trace-mcp",
        conversation_id="conv-mcp",
        settings=settings,
        store=store,
    )

    assert state.plan.status == PlanStatus.IN_PROGRESS
    assert "Found 3 mock flights from TIA to FRA" in message
    assert state.flight_search.selected_option_id == "LH001"
    assert state.pending_approval is not None


@pytest.mark.parametrize(
    ("relative_path", "forbidden"),
    [
        ("app/agent/coordinator.py", ("tools_mode", "ToolsMode", "create_tool_adapter")),
        ("app/agent/loop.py", ("DirectToolAdapter", "McpToolAdapter", "RemoteMcpClient")),
        ("app/agent/workers/flight_worker.py", ("tools_mode", "ToolsMode")),
        ("app/agent/workers/booking_worker.py", ("tools_mode", "ToolsMode")),
    ],
)
def test_runtime_mode_switching_stays_outside_coordinator_and_workers(
    relative_path: str,
    forbidden: tuple[str, ...],
) -> None:
    source = Path(relative_path).read_text(encoding="utf-8")
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        if isinstance(node, ast.Attribute):
            names.add(node.attr)

    for token in forbidden:
        assert token not in names
        assert token not in source
