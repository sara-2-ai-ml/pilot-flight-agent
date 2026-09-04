"""Planning tests — Phase 2.1, Phase 11.1."""

import json
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from app.agent.planning import (
    LlmPlanner,
    PlanningError,
    ensure_plan,
    extract_json_object,
    parse_plan_payload,
)
from app.agent.state import AgentState
from app.config import Settings
from app.models.agent import Language
from app.models.planning import Plan, PlanStatus, PlanStep, StepStatus, Worker

SAMPLE_PLAN_JSON = {
    "goal": "Find and reserve a flight",
    "steps": [
        {
            "id": "search",
            "worker": "flight",
            "action": "search_flights",
            "depends_on": [],
        },
        {
            "id": "select",
            "worker": "flight",
            "action": "validate_options",
            "depends_on": ["search"],
        },
        {
            "id": "booking",
            "worker": "booking",
            "action": "create_booking",
            "depends_on": ["select"],
        },
    ],
}

MOCK_LLM_SEARCH_ONLY_JSON = {
    "goal": "Find flights from TIA to FRA on Sep 15",
    "steps": [
        {"id": "search", "worker": "flight", "action": "search_flights", "depends_on": []},
        {
            "id": "select",
            "worker": "flight",
            "action": "validate_options",
            "depends_on": ["search"],
        },
    ],
}


def _mock_llm_response(plan_json: dict) -> MagicMock:
    mock_client = MagicMock()
    mock_block = MagicMock(type="text", text=json.dumps(plan_json))
    mock_client.messages.create.return_value = MagicMock(content=[mock_block])
    return mock_client


def test_plan_validates_sample_json() -> None:
    plan = Plan.model_validate(SAMPLE_PLAN_JSON)

    assert plan.goal == "Find and reserve a flight"
    assert len(plan.steps) == 3
    assert plan.steps[0].worker == Worker.FLIGHT
    assert plan.steps[0].action == "search_flights"
    assert plan.steps[2].depends_on == ["select"]
    assert plan.status == PlanStatus.PENDING


def test_plan_serializes_to_json_and_back() -> None:
    plan = Plan.model_validate(SAMPLE_PLAN_JSON)
    restored = Plan.model_validate_json(plan.model_dump_json())

    assert restored == plan


def test_plan_step_defaults() -> None:
    step = PlanStep(id="search", worker=Worker.FLIGHT, action="search_flights")

    assert step.depends_on == []
    assert step.status == StepStatus.PENDING


def test_plan_rejects_duplicate_step_ids() -> None:
    payload = {
        "goal": "Test",
        "steps": [
            {"id": "search", "worker": "flight", "action": "search_flights"},
            {"id": "search", "worker": "booking", "action": "create_booking"},
        ],
    }

    with pytest.raises(ValidationError):
        Plan.model_validate(payload)


def test_plan_rejects_unknown_dependency() -> None:
    payload = {
        "goal": "Test",
        "steps": [
            {
                "id": "booking",
                "worker": "booking",
                "action": "create_booking",
                "depends_on": ["missing"],
            },
        ],
    }

    with pytest.raises(ValidationError):
        Plan.model_validate(payload)


def test_plan_rejects_out_of_range_current_step() -> None:
    payload = {**SAMPLE_PLAN_JSON, "current_step": 99}

    with pytest.raises(ValidationError):
        Plan.model_validate(payload)


def test_extract_json_object_parses_mock_llm_markdown_fence() -> None:
    payload = extract_json_object(
        f"```json\n{json.dumps(MOCK_LLM_SEARCH_ONLY_JSON)}\n```",
    )

    assert payload == MOCK_LLM_SEARCH_ONLY_JSON


def test_parse_plan_payload_accepts_valid_mock_llm_json() -> None:
    plan = parse_plan_payload(MOCK_LLM_SEARCH_ONLY_JSON)

    assert plan.goal.startswith("Find flights")
    assert [step.id for step in plan.steps] == ["search", "select"]
    assert plan.steps[0].worker == Worker.FLIGHT
    assert plan.steps[1].depends_on == ["search"]


def test_mock_llm_json_pipeline_produces_valid_plan() -> None:
    raw = json.dumps(MOCK_LLM_SEARCH_ONLY_JSON)
    plan = parse_plan_payload(extract_json_object(raw))

    assert len(plan.steps) == 2
    assert plan.steps[1].action == "validate_options"


def test_parse_plan_payload_rejects_natural_language_action() -> None:
    payload = {
        "goal": "Greet user",
        "steps": [
            {
                "id": "greet",
                "worker": "flight",
                "action": "Greet the user and ask for travel requirements",
                "depends_on": [],
            }
        ],
    }

    with pytest.raises(PlanningError, match="Unsupported action"):
        parse_plan_payload(payload)


def test_llm_planner_returns_valid_plan_from_mock_response() -> None:
    planner = LlmPlanner(
        settings=Settings(anthropic_api_key="test-key", planner_use_mock=False),
        client=_mock_llm_response(MOCK_LLM_SEARCH_ONLY_JSON),
    )
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.user_message = "Find flights TIA to FRA on Sep 15"
    state.language = Language.EN

    plan = planner.create_plan(state)

    assert plan.goal == MOCK_LLM_SEARCH_ONLY_JSON["goal"]
    assert [step.id for step in plan.steps] == ["search", "select"]


def test_ensure_plan_attaches_valid_plan_from_mock_llm() -> None:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.user_message = "Book flights TIA to FRA on 2025-09-15"
    planner = LlmPlanner(
        settings=Settings(anthropic_api_key="test-key", planner_use_mock=False),
        client=_mock_llm_response(SAMPLE_PLAN_JSON),
    )

    ensure_plan(state, planner=planner)

    assert state.plan.goal == SAMPLE_PLAN_JSON["goal"]
    assert len(state.plan.steps) == 3
    assert state.plan.status == PlanStatus.PENDING
    assert state.llm_call_count == 1


def test_ensure_plan_coerces_find_requests_to_search_only() -> None:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.user_message = "Find flights TIA to FRA on Sep 15"
    planner = LlmPlanner(
        settings=Settings(anthropic_api_key="test-key", planner_use_mock=False),
        client=_mock_llm_response(SAMPLE_PLAN_JSON),
    )

    ensure_plan(state, planner=planner)

    assert len(state.plan.steps) == 1
    assert state.plan.steps[0].action == "search_flights"


def test_mock_llm_invalid_json_raises_planning_error() -> None:
    mock_client = MagicMock()
    mock_block = MagicMock(type="text", text="Here is your plan: not-json")
    mock_client.messages.create.return_value = MagicMock(content=[mock_block])
    planner = LlmPlanner(
        settings=Settings(anthropic_api_key="test-key"),
        client=mock_client,
    )
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.user_message = "Find flights"

    with pytest.raises(PlanningError, match="invalid JSON"):
        planner.create_plan(state)


def test_mock_llm_invalid_schema_raises_planning_error() -> None:
    invalid_payload = {
        "goal": "Broken plan",
        "steps": [
            {
                "id": "booking",
                "worker": "booking",
                "action": "create_booking",
                "depends_on": ["missing"],
            },
        ],
    }
    planner = LlmPlanner(
        settings=Settings(anthropic_api_key="test-key"),
        client=_mock_llm_response(invalid_payload),
    )
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.user_message = "Book a flight"

    with pytest.raises(PlanningError, match="Plan schema"):
        planner.create_plan(state)
