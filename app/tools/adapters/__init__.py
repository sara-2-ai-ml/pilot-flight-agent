"""Tool adapters — direct services or MCP-backed invocation."""

from functools import lru_cache

from app.config import Settings, ToolsMode, get_settings
from app.tools.adapters.base import ToolAdapter
from app.tools.adapters.direct import DirectToolAdapter
from app.tools.adapters.mcp import McpToolAdapter


def create_tool_adapter(
    settings: Settings | None = None,
    *,
    adapter: ToolAdapter | None = None,
) -> ToolAdapter:
    """Build the configured tool adapter implementation."""
    if adapter is not None:
        return adapter

    resolved = settings or get_settings()
    if resolved.tools_mode == ToolsMode.MCP:
        return McpToolAdapter(settings=resolved)
    return DirectToolAdapter(settings=resolved)


@lru_cache
def get_tool_adapter() -> ToolAdapter:
    """Return the app-wide tool adapter singleton."""
    return create_tool_adapter()


def clear_tool_adapter_cache() -> None:
    """Reset cached adapter — for tests."""
    get_tool_adapter.cache_clear()


__all__ = [
    "DirectToolAdapter",
    "McpToolAdapter",
    "ToolAdapter",
    "clear_tool_adapter_cache",
    "create_tool_adapter",
    "get_tool_adapter",
]
