"""Low-level stdio transport for MCP server subprocesses."""

from __future__ import annotations

import asyncio
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from app.core.timeout import ExternalCallTimeoutError, await_with_timeout
from app.mcp.result_parsing import McpClientError, extract_tool_result


async def invoke_mcp_tool(
    *,
    command: str,
    args: list[str],
    tool_name: str,
    arguments: dict[str, Any] | None = None,
    env: dict[str, str] | None = None,
    timeout_seconds: float,
) -> Any:
    """Start one MCP server process, call a tool, and return the parsed result."""

    async def _invoke() -> Any:
        params = StdioServerParameters(command=command, args=args, env=env)
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments or {})
                if getattr(result, "isError", False):
                    payload = extract_tool_result(result)
                    raise McpClientError(f"MCP tool '{tool_name}' failed: {payload}")
                return extract_tool_result(result)

    try:
        return await await_with_timeout(
            _invoke(),
            timeout_seconds=timeout_seconds,
            operation=f"MCP tool '{tool_name}'",
        )
    except ExternalCallTimeoutError:
        raise


async def list_mcp_tools(
    *,
    command: str,
    args: list[str],
    env: dict[str, str] | None = None,
    timeout_seconds: float,
) -> list[str]:
    """Return tool names exposed by one MCP server."""

    async def _list() -> list[str]:
        params = StdioServerParameters(command=command, args=args, env=env)
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                return [tool.name for tool in tools.tools]

    return await await_with_timeout(
        _list(),
        timeout_seconds=timeout_seconds,
        operation="MCP list_tools",
    )


async def list_mcp_prompts(
    *,
    command: str,
    args: list[str],
    env: dict[str, str] | None = None,
    timeout_seconds: float,
) -> list[str]:
    """Return prompt names exposed by one MCP server."""

    async def _list() -> list[str]:
        params = StdioServerParameters(command=command, args=args, env=env)
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                prompts = await session.list_prompts()
                return [prompt.name for prompt in prompts.prompts]

    return await await_with_timeout(
        _list(),
        timeout_seconds=timeout_seconds,
        operation="MCP list_prompts",
    )


async def get_mcp_prompt(
    *,
    command: str,
    args: list[str],
    prompt_name: str,
    arguments: dict[str, str] | None = None,
    env: dict[str, str] | None = None,
    timeout_seconds: float,
) -> str:
    """Fetch one MCP prompt rendered as user-facing text."""

    async def _get() -> str:
        params = StdioServerParameters(command=command, args=args, env=env)
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.get_prompt(prompt_name, arguments or {})
                messages = getattr(result, "messages", None) or []
                if not messages:
                    raise McpClientError(f"MCP prompt '{prompt_name}' returned no messages.")
                content = messages[0].content
                text = getattr(content, "text", None)
                if not text:
                    raise McpClientError(f"MCP prompt '{prompt_name}' returned empty content.")
                return text

    return await await_with_timeout(
        _get(),
        timeout_seconds=timeout_seconds,
        operation=f"MCP prompt '{prompt_name}'",
    )


async def read_mcp_resource(
    *,
    command: str,
    args: list[str],
    uri: str,
    env: dict[str, str] | None = None,
    timeout_seconds: float,
) -> str:
    """Read one MCP resource URI from a server process."""

    async def _read() -> str:
        params = StdioServerParameters(command=command, args=args, env=env)
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                contents = await session.read_resource(uri)
                if not contents.contents:
                    raise McpClientError(f"MCP resource '{uri}' returned no content.")
                return contents.contents[0].text

    return await await_with_timeout(
        _read(),
        timeout_seconds=timeout_seconds,
        operation=f"MCP resource '{uri}'",
    )


def run_mcp_coroutine(coro: Any) -> Any:
    """Run one MCP coroutine from synchronous worker code."""
    return asyncio.run(coro)
