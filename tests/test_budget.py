"""AgentBudget tests — Phase 1.5."""

from app.agent.budget import AgentBudget
from app.agent.state import AgentState
from app.config import Settings


def test_budget_not_exceeded_within_limits() -> None:
    budget = AgentBudget.from_settings(Settings(max_iterations=8))
    state = AgentState.new(conversation_id="c1", trace_id="t1")
    state.iteration_count = 7

    assert budget.is_exceeded(state) is False


def test_budget_exceeded_when_iterations_over_limit() -> None:
    budget = AgentBudget.from_settings(Settings(max_iterations=8))
    state = AgentState.new(conversation_id="c1", trace_id="t1")
    state.iteration_count = 8

    assert budget.is_exceeded(state) is True
