"""LLM cost tracking — llm_call_count and token_usage."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.core.observability import log_extra

if TYPE_CHECKING:
    import logging

    from app.agent.state import AgentState
    from app.core.metrics import TurnMetrics


@dataclass(frozen=True)
class CostSummary:
    """LLM usage counters for one scope (turn or session)."""

    llm_call_count: int
    token_usage: int


def session_cost(state: AgentState) -> CostSummary:
    """Read cumulative LLM cost counters from session state."""
    return CostSummary(
        llm_call_count=getattr(state, "llm_call_count", 0),
        token_usage=getattr(state, "token_usage", 0),
    )


def turn_cost(turn: TurnMetrics) -> CostSummary:
    """Extract LLM cost counters from one turn metrics snapshot."""
    return CostSummary(
        llm_call_count=turn.llm_call_count,
        token_usage=turn.token_usage,
    )


def build_cost_debug_payload(
    *,
    session: CostSummary,
    turn: CostSummary | None = None,
) -> dict[str, Any]:
    """Build the debug.cost block returned when DEBUG=true."""
    payload: dict[str, Any] = {
        "session": {
            "llm_call_count": session.llm_call_count,
            "token_usage": session.token_usage,
        },
    }
    if turn is not None:
        payload["turn"] = {
            "llm_call_count": turn.llm_call_count,
            "token_usage": turn.token_usage,
        }
    return payload


def log_cost_tracking(
    logger: logging.Logger,
    *,
    state: AgentState,
    trace_id: str | None = None,
    turn: TurnMetrics | None = None,
) -> None:
    """Emit a focused cost_tracking log line for the completed turn."""
    session = session_cost(state)
    extra: dict[str, object] = {
        "event": "cost_tracking",
        "trace_id": trace_id or getattr(state, "trace_id", None),
        "llm_call_count": session.llm_call_count,
        "token_usage": session.token_usage,
    }
    if turn is not None:
        extra["turn_llm_call_count"] = turn.llm_call_count
        extra["turn_token_usage"] = turn.token_usage

    logger.info("cost_tracking", extra=log_extra(**extra))
