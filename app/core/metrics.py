"""Turn and session metrics — latency, token usage, tool counts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.core.observability import log_extra

if TYPE_CHECKING:
    import logging

    from app.agent.state import AgentState


@dataclass(frozen=True)
class TurnMetrics:
    """Counters accumulated during one user turn."""

    latency_ms: float
    tool_call_count: int
    llm_call_count: int
    token_usage: int


@dataclass(frozen=True)
class SessionMetrics:
    """Cumulative counters stored on session state."""

    tool_call_count: int
    llm_call_count: int
    token_usage: int
    iteration_count: int


class MetricsSnapshot:
    """Capture session counters at the start of a turn for delta metrics."""

    def __init__(self, state: AgentState) -> None:
        tool_history = getattr(state, "tool_history", None) or []
        self._tool_call_count = len(tool_history)
        self._llm_call_count = getattr(state, "llm_call_count", 0)
        self._token_usage = getattr(state, "token_usage", 0)

    def turn_metrics(self, state: AgentState, *, latency_ms: float) -> TurnMetrics:
        tool_history = getattr(state, "tool_history", None) or []
        return TurnMetrics(
            latency_ms=latency_ms,
            tool_call_count=len(tool_history) - self._tool_call_count,
            llm_call_count=getattr(state, "llm_call_count", 0) - self._llm_call_count,
            token_usage=getattr(state, "token_usage", 0) - self._token_usage,
        )


def session_metrics(state: AgentState) -> SessionMetrics:
    """Read cumulative metrics from session state."""
    tool_history = getattr(state, "tool_history", None) or []
    return SessionMetrics(
        tool_call_count=len(tool_history),
        llm_call_count=getattr(state, "llm_call_count", 0),
        token_usage=getattr(state, "token_usage", 0),
        iteration_count=getattr(state, "iteration_count", 0),
    )


def metrics_log_fields(
    *,
    turn: TurnMetrics,
    session: SessionMetrics,
) -> dict[str, float | int]:
    """Structured log fields for one turn and the full session."""
    return {
        "latency_ms": turn.latency_ms,
        "turn_tool_call_count": turn.tool_call_count,
        "turn_llm_call_count": turn.llm_call_count,
        "turn_token_usage": turn.token_usage,
        "tool_call_count": session.tool_call_count,
        "llm_call_count": session.llm_call_count,
        "token_usage": session.token_usage,
        "iteration_count": session.iteration_count,
    }


def log_turn_metrics(
    logger: logging.Logger,
    *,
    state: AgentState,
    snapshot: MetricsSnapshot,
    latency_ms: float,
    trace_id: str | None = None,
) -> TurnMetrics:
    """Emit one structured ``turn_metrics`` log line for the completed turn."""
    turn = snapshot.turn_metrics(state, latency_ms=latency_ms)
    session = session_metrics(state)
    logger.info(
        "turn_metrics",
        extra=log_extra(
            event="turn_metrics",
            trace_id=trace_id or state.trace_id,
            **metrics_log_fields(turn=turn, session=session),
        ),
    )
    return turn
