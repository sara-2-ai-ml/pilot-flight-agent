"""Replanning tests — Phase 3.5."""

from app.agent.planning import MockPlanner, assign_plan_to_state, build_default_flight_plan, ensure_plan
from app.agent.replanning import consume_stub_replan, replan_for_state, set_stub_replan
from app.agent.state import AgentState
from app.models.planning import Plan, PlanStatus, PlanStep, Worker


class SearchOnlyMockPlanner:
    """Returns a full plan initially, then a single-step plan on replan."""

    def __init__(self) -> None:
        self.call_count = 0

    def create_plan(self, state: AgentState) -> Plan:
        self.call_count += 1
        if state.replan_count == 0:
            return build_default_flight_plan(state.user_message)

        return Plan(
            goal=state.user_message,
            steps=[PlanStep(id="search", worker=Worker.FLIGHT, action="search_flights")],
        )


def test_set_stub_replan_triggers_once() -> None:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    set_stub_replan(state, ["search"])

    assert consume_stub_replan(state, "search") is True
    assert consume_stub_replan(state, "search") is False


def test_replan_for_state_replaces_plan() -> None:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.user_message = "Find flights TIA to FRA"
    assign_plan_to_state(state, build_default_flight_plan("Original goal"))
    state.step_retry_counts["search"] = 2
    state.replan_count = 1

    replan_for_state(state, planner=SearchOnlyMockPlanner())

    assert state.replan_count == 2
    assert state.plan.goal == "Find flights TIA to FRA"
    assert len(state.plan.steps) == 1
    assert state.plan.steps[0].action == "search_flights"
    assert state.plan.status == PlanStatus.PENDING
    assert state.step_retry_counts == {}


def test_ensure_plan_not_called_on_replan_when_steps_exist() -> None:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.user_message = "Find flights"
    ensure_plan(state, planner=MockPlanner())
    state.replan_count = 1

    replan_for_state(state, planner=SearchOnlyMockPlanner())

    assert len(state.plan.steps) == 1
