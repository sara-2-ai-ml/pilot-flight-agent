"""Agent budget — iteration, LLM, tool, latency, and token limits."""

from dataclasses import dataclass

from app.agent.state import AgentState
from app.config import Settings


@dataclass(frozen=True)
class AgentBudget:
    max_iterations: int
    max_llm_calls: int
    max_tool_calls: int
    max_tokens: int

    @classmethod
    def from_settings(cls, settings: Settings) -> "AgentBudget":
        return cls(
            max_iterations=settings.max_iterations,
            max_llm_calls=settings.max_llm_calls,
            max_tool_calls=settings.max_tool_calls,
            max_tokens=settings.max_tokens,
        )

    def is_exceeded(self, state: AgentState) -> bool:
        return (
            state.iteration_count >= self.max_iterations
            or state.llm_call_count > self.max_llm_calls
            or len(state.tool_history) > self.max_tool_calls
            or state.token_usage > self.max_tokens
        )
