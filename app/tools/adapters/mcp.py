"""MCP tool adapter — routes worker actions through an MCP client."""

from app.agent.state import AgentState
from app.agent.workers.base import WorkerResult
from app.config import Settings, ToolsMode, get_settings
from app.mcp.client import McpClient, create_mcp_client


class McpToolAdapter:
    """Invoke tools via MCP tool calls instead of direct service imports."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        mcp_client: McpClient | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._mcp_client = mcp_client or create_mcp_client(settings=self._settings)

    @property
    def mode(self) -> ToolsMode:
        return ToolsMode.MCP

    def search_flights(self, state: AgentState) -> WorkerResult:
        return self._mcp_client.call_tool("search_flights", state=state)

    def validate_options(self, state: AgentState) -> WorkerResult:
        return self._mcp_client.call_tool("validate_options", state=state)

    def create_booking(self, state: AgentState) -> WorkerResult:
        return self._mcp_client.call_tool("create_booking", state=state)
