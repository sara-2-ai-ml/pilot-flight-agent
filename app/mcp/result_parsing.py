"""Parse MCP tool call results into Python values."""

from __future__ import annotations

import json
from typing import Any


class McpClientError(Exception):
    """Raised when an MCP client operation fails."""


def extract_tool_result(result: Any) -> Any:
    """Return the structured payload from an MCP CallToolResult."""
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict) and "result" in structured:
        return structured["result"]

    content = getattr(result, "content", None) or []
    if not content:
        return None

    texts = [getattr(item, "text", "") for item in content if getattr(item, "text", None)]
    if not texts:
        return None
    if len(texts) == 1:
        return _loads_json_if_possible(texts[0])
    return [_loads_json_if_possible(text) for text in texts]


def _loads_json_if_possible(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value
