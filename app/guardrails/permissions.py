"""Tool permission model — READ vs WRITE, approval gate."""

from __future__ import annotations

from enum import Enum

from app.models.planning import Worker


class ToolPermission(str, Enum):
    """Whether a tool mutates external state or only reads."""

    READ = "read"
    WRITE = "write"


class UnknownToolError(KeyError):
    """Raised when a tool name is not registered in the permission model."""


TOOL_PERMISSIONS: dict[str, ToolPermission] = {
    # Flight domain
    "search_flights": ToolPermission.READ,
    "get_flight_status": ToolPermission.READ,
    "validate_options": ToolPermission.READ,
    # Booking domain
    "get_booking": ToolPermission.READ,
    "create_booking": ToolPermission.WRITE,
    "cancel_booking": ToolPermission.WRITE,
}

WRITE_TOOLS = frozenset(
    name for name, permission in TOOL_PERMISSIONS.items() if permission == ToolPermission.WRITE
)
READ_TOOLS = frozenset(
    name for name, permission in TOOL_PERMISSIONS.items() if permission == ToolPermission.READ
)


def normalize_tool_name(tool_name: str) -> str:
    """Normalize tool identifiers for permission lookup."""
    return tool_name.strip()


def get_tool_permission(tool_name: str) -> ToolPermission:
    """Return the permission class for one registered tool."""
    normalized = normalize_tool_name(tool_name)
    try:
        return TOOL_PERMISSIONS[normalized]
    except KeyError as exc:
        raise UnknownToolError(f"Unknown tool '{tool_name}'.") from exc


def is_read_tool(tool_name: str) -> bool:
    return get_tool_permission(tool_name) == ToolPermission.READ


def is_write_tool(tool_name: str) -> bool:
    return get_tool_permission(tool_name) == ToolPermission.WRITE


def requires_approval(tool_name: str) -> bool:
    """WRITE tools require human approval before side effects (Phase 7)."""
    return is_write_tool(tool_name)


def get_worker_action_permission(*, worker: Worker, action: str) -> ToolPermission:
    """Resolve permission for a coordinator worker action."""
    normalized = normalize_tool_name(action)
    if worker == Worker.FLIGHT and normalized not in {"search_flights", "validate_options"}:
        raise UnknownToolError(f"Unsupported flight worker action '{action}'.")
    if worker == Worker.BOOKING and normalized != "create_booking":
        raise UnknownToolError(f"Unsupported booking worker action '{action}'.")
    return get_tool_permission(normalized)


def executes_directly(*, worker: Worker, action: str) -> bool:
    """Return True when a worker action may run without human approval."""
    return get_worker_action_permission(worker=worker, action=action) == ToolPermission.READ
