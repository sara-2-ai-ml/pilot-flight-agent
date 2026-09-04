"""LLM planner tests — Phase 2.3."""

from unittest.mock import MagicMock

import pytest

from app.agent.planning import (
    LlmPlanner,
    PlanningError,
    extract_json_object,
    get_planner,
    parse_plan_payload,
)
from app.agent.state import AgentState
from app.config import Settings
from app.models.agent import Language

SAMPLE_LLM_PLAN = {
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


def test_extract_json_object_strips_markdown_fence() -> None:
    payload = extract_json_object(
        '```json\n{"goal": "Test", "steps": []}\n```',
    )

    assert payload == {"goal": "Test", "steps": []}


def test_parse_plan_payload_validates_schema() -> None:
    plan = parse_plan_payload(SAMPLE_LLM_PLAN)

    assert plan.goal.startswith("Find flights")
    assert len(plan.steps) == 2
    assert plan.steps[0].action == "search_flights"


def test_llm_planner_parses_structured_response() -> None:
    mock_client = MagicMock()
    mock_block = MagicMock(type="text", text='{"goal": "Find flights from TIA to FRA on Sep 15", "steps": [{"id": "search", "worker": "flight", "action": "search_flights", "depends_on": []}, {"id": "select", "worker": "flight", "action": "validate_options", "depends_on": ["search"]}]}')
    mock_response = MagicMock(content=[mock_block])
    mock_client.messages.create.return_value = mock_response

    settings = Settings(anthropic_api_key="test-key", planner_use_mock=False)
    planner = LlmPlanner(settings=settings, client=mock_client)

    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.user_message = "Find flights TIA to FRA on Sep 15"
    state.language = Language.EN

    plan = planner.create_plan(state)

    assert plan.goal == "Find flights from TIA to FRA on Sep 15"
    assert [step.id for step in plan.steps] == ["search", "select"]
    mock_client.messages.create.assert_called_once()


def test_llm_planner_raises_on_invalid_json() -> None:
    mock_client = MagicMock()
    mock_block = MagicMock(type="text", text="not json")
    mock_client.messages.create.return_value = MagicMock(content=[mock_block])

    planner = LlmPlanner(
        settings=Settings(anthropic_api_key="test-key"),
        client=mock_client,
    )
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.user_message = "Hello"

    with pytest.raises(PlanningError, match="invalid JSON"):
        planner.create_plan(state)


def test_get_planner_uses_llm_when_mock_disabled() -> None:
    settings = Settings(anthropic_api_key="test-key", planner_use_mock=False)
    planner = get_planner(settings=settings, use_mock=False)

    assert isinstance(planner, LlmPlanner)


def test_get_planner_requires_api_key_when_mock_disabled() -> None:
    settings = Settings(anthropic_api_key=None, planner_use_mock=False)

    with pytest.raises(PlanningError, match="ANTHROPIC_API_KEY"):
        get_planner(settings=settings, use_mock=False)
