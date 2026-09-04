"""Planner interface tests — Phase 2.2."""

from app.agent.planning import (
    MockPlanner,
    assign_plan_to_state,
    build_default_flight_plan,
    build_search_only_plan,
    coerce_plan_for_intent,
    ensure_plan,
    expand_route_plan_to_booking,
    get_planner,
)
from app.agent.state import AgentState
from app.models.planning import Plan, PlanStatus, PlanStep, Worker


def test_build_default_flight_plan_is_valid() -> None:
    plan = build_default_flight_plan("Find and reserve a flight")

    assert plan.goal == "Find and reserve a flight"
    assert len(plan.steps) == 3
    assert plan.steps[0].worker == Worker.FLIGHT
    assert plan.steps[2].depends_on == ["select"]
    assert plan.status == PlanStatus.PENDING


def test_mock_planner_returns_search_only_for_find_requests() -> None:
    planner = MockPlanner()
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.user_message = "Find flights TIA to FRA on Sep 15"

    plan = planner.create_plan(state)

    assert plan.goal == "Find flights TIA to FRA on Sep 15"
    assert [step.id for step in plan.steps] == ["search"]


def test_mock_planner_returns_booking_plan_for_book_requests() -> None:
    planner = MockPlanner()
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.user_message = "Book flights TIA to FRA on Sep 15"

    plan = planner.create_plan(state)

    assert [step.id for step in plan.steps] == ["search", "select", "booking"]


def test_get_planner_returns_mock_by_default() -> None:
    planner = get_planner()
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.user_message = "Book a flight"

    plan = planner.create_plan(state)

    assert plan.steps[0].action == "search_flights"


def test_assign_plan_to_state_sets_pending_plan() -> None:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    plan = build_default_flight_plan("Find flights")

    assign_plan_to_state(state, plan)

    assert state.plan.goal == "Find flights"
    assert len(state.plan.steps) == 3
    assert state.plan.current_step == 0
    assert state.plan.status == PlanStatus.PENDING


def test_ensure_plan_attaches_plan_when_missing() -> None:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.user_message = "Find flights TIA to FRA on Sep 15"

    ensure_plan(state, planner=MockPlanner())

    assert len(state.plan.steps) == 1
    assert state.plan.goal == "Find flights TIA to FRA on Sep 15"


def test_ensure_plan_skips_when_plan_already_exists() -> None:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    assign_plan_to_state(state, build_default_flight_plan("Original"))
    state.plan.status = PlanStatus.IN_PROGRESS
    state.plan.steps[0].action = "custom_action"

    ensure_plan(state, planner=MockPlanner())

    assert state.plan.steps[0].action == "custom_action"


def test_expand_route_plan_to_booking_upgrades_search_only_for_book_intent() -> None:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.user_message = "Book TIA to CDG on 2025-09-09"
    state.current_intent = "book_flight"
    state.flight_search.origin = "TIA"
    state.flight_search.destination = "CDG"
    search_only = Plan(
        goal="Book flight",
        steps=[PlanStep(id="search", worker=Worker.FLIGHT, action="search_flights")],
    )

    expanded = expand_route_plan_to_booking(state, search_only)

    assert [step.action for step in expanded.steps] == [
        "search_flights",
        "validate_options",
        "create_booking",
    ]


def test_expand_route_plan_keeps_search_only_for_find_intent() -> None:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.user_message = "Find flights TIA to CDG"
    state.current_intent = "search_flights"
    state.flight_search.origin = "TIA"
    state.flight_search.destination = "CDG"
    search_only = build_search_only_plan("Find flights")

    expanded = expand_route_plan_to_booking(state, search_only)

    assert [step.action for step in expanded.steps] == ["search_flights"]


def test_ensure_plan_expands_search_only_when_book_intent_and_route_known() -> None:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.user_message = "Book TIA to CDG"
    state.current_intent = "book_flight"
    state.flight_search.origin = "TIA"
    state.flight_search.destination = "CDG"

    class SearchOnlyPlanner:
        def create_plan(self, inner_state: AgentState) -> Plan:
            return Plan(
                goal=inner_state.user_message,
                steps=[PlanStep(id="search", worker=Worker.FLIGHT, action="search_flights")],
            )

    ensure_plan(state, planner=SearchOnlyPlanner())

    assert len(state.plan.steps) == 3
    assert state.plan.steps[-1].action == "create_booking"


def test_coerce_plan_for_intent_strips_validate_from_llm_search_plan() -> None:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.user_message = "Find flights TIA to FRA on 2025-09-15"
    state.current_intent = "book_flight"
    state.flight_search.origin = "TIA"
    state.flight_search.destination = "FRA"
    llm_plan = Plan(
        goal="Find flights",
        steps=[
            PlanStep(id="search_1", worker=Worker.FLIGHT, action="search_flights"),
            PlanStep(
                id="validate_1",
                worker=Worker.FLIGHT,
                action="validate_options",
                depends_on=["search_1"],
            ),
        ],
    )

    coerced = coerce_plan_for_intent(state, llm_plan)

    assert [step.action for step in coerced.steps] == ["search_flights"]
