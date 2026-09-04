"""Tool permission tests — Phase 7.1."""

import pytest

from app.guardrails.permissions import (
    READ_TOOLS,
    TOOL_PERMISSIONS,
    WRITE_TOOLS,
    ToolPermission,
    UnknownToolError,
    get_tool_permission,
    get_worker_action_permission,
    is_read_tool,
    is_write_tool,
    requires_approval,
)
from app.models.planning import Worker


def test_create_booking_is_write() -> None:
    assert get_tool_permission("create_booking") == ToolPermission.WRITE
    assert is_write_tool("create_booking") is True
    assert requires_approval("create_booking") is True


@pytest.mark.parametrize(
    ("tool_name", "expected"),
    [
        ("search_flights", ToolPermission.READ),
        ("get_flight_status", ToolPermission.READ),
        ("validate_options", ToolPermission.READ),
        ("get_booking", ToolPermission.READ),
        ("create_booking", ToolPermission.WRITE),
        ("cancel_booking", ToolPermission.WRITE),
    ],
)
def test_tool_permission_registry(tool_name: str, expected: ToolPermission) -> None:
    assert TOOL_PERMISSIONS[tool_name] == expected


def test_read_tools_do_not_require_approval() -> None:
    for tool_name in READ_TOOLS:
        assert requires_approval(tool_name) is False
        assert is_read_tool(tool_name) is True


def test_write_tools_require_approval() -> None:
    assert WRITE_TOOLS == frozenset({"create_booking", "cancel_booking"})
    for tool_name in WRITE_TOOLS:
        assert requires_approval(tool_name) is True


def test_get_tool_permission_rejects_unknown_tool() -> None:
    with pytest.raises(UnknownToolError, match="Unknown tool"):
        get_tool_permission("delete_everything")


def test_get_worker_action_permission_for_flight_worker() -> None:
    assert (
        get_worker_action_permission(worker=Worker.FLIGHT, action="search_flights")
        == ToolPermission.READ
    )
    assert (
        get_worker_action_permission(worker=Worker.FLIGHT, action="validate_options")
        == ToolPermission.READ
    )


def test_get_worker_action_permission_for_booking_worker() -> None:
    assert (
        get_worker_action_permission(worker=Worker.BOOKING, action="create_booking")
        == ToolPermission.WRITE
    )


def test_get_worker_action_permission_rejects_unsupported_action() -> None:
    with pytest.raises(UnknownToolError, match="Unsupported booking worker action"):
        get_worker_action_permission(worker=Worker.BOOKING, action="cancel_booking")
