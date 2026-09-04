"""Replanning — adaptive plan updates when evaluation requires REPLAN."""

from app.agent.planning import (
    LlmPlanner,
    Planner,
    assign_plan_to_state,
    coerce_plan_for_intent,
    expand_route_plan_to_booking,
    get_planner,
)
from app.agent.state import AgentState
from app.config import Settings, get_settings

_STUB_REPLAN_KEY = "stub_replan_steps"


def set_stub_replan(state: AgentState, step_ids: list[str]) -> None:
    """Test hook — trigger REPLAN after the named steps succeed."""
    state.user_context[_STUB_REPLAN_KEY] = ",".join(step_ids)


def consume_stub_replan(state: AgentState, step_id: str) -> bool:
    """Return True once when a stub replan is configured for this step."""
    raw = state.user_context.get(_STUB_REPLAN_KEY, "")
    if not raw:
        return False

    pending = [entry for entry in raw.split(",") if entry]
    if step_id not in pending:
        return False

    pending.remove(step_id)
    if pending:
        state.user_context[_STUB_REPLAN_KEY] = ",".join(pending)
    else:
        state.user_context.pop(_STUB_REPLAN_KEY, None)

    return True


def replan_for_state(
    state: AgentState,
    *,
    planner: Planner | None = None,
    settings: Settings | None = None,
) -> None:
    """Replace the current plan with a freshly generated one."""
    resolved_settings = settings or get_settings()
    resolved_planner = planner or get_planner(settings=resolved_settings)

    state.replan_count += 1
    state.step_retry_counts.clear()

    plan = resolved_planner.create_plan(state)
    plan = expand_route_plan_to_booking(state, plan)
    plan = coerce_plan_for_intent(state, plan)
    assign_plan_to_state(state, plan)

    if isinstance(resolved_planner, LlmPlanner):
        state.llm_call_count += 1
