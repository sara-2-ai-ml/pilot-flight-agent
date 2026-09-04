"""NLU tests — natural language slot extraction."""

from unittest.mock import MagicMock

import pytest

from app.agent.nlu import (
    LlmNluExtractor,
    MockNluExtractor,
    NluError,
    apply_travel_slots,
    clarification_message_for_slots,
    enrich_travel_slots,
    extract_travel_slots,
    get_nlu_extractor,
    parse_travel_slots_payload,
)
from app.models.nlu import TravelSlots
from app.agent.state import AgentState
from app.config import Settings
from app.models.agent import Language


def _state(message: str, *, language: Language = Language.EN) -> AgentState:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.user_message = message
    state.language = language
    return state


def test_mock_nlu_asks_on_greeting() -> None:
    state = _state("hi")
    slots = MockNluExtractor().extract(state)

    assert slots.needs_clarification is True
    assert slots.origin is None
    message = clarification_message_for_slots(
        state,
        slots,
        settings=Settings(nlu_use_mock=True),
    )
    assert "flying from" in message.lower() or "Where" in message
    assert "TIA" not in message


def test_mock_nlu_asks_on_vague_ticket_request() -> None:
    state = _state("i want a ticket")
    slots = MockNluExtractor().extract(state)

    assert slots.needs_clarification is True
    message = clarification_message_for_slots(
        state,
        slots,
        settings=Settings(nlu_use_mock=True),
    )
    assert message
    assert "TIA" not in message


def test_mock_nlu_extracts_iata_route() -> None:
    slots = MockNluExtractor().extract(_state("Find flights TIA to FRA on 2025-09-15"))

    assert slots.needs_clarification is False
    assert slots.origin == "TIA"
    assert slots.destination == "FRA"
    assert slots.travel_date == "2025-09-15"


def test_mock_nlu_extracts_city_names() -> None:
    slots = MockNluExtractor().extract(_state("Flights from Tirana to Frankfurt"))

    assert slots.needs_clarification is False
    assert slots.origin == "TIA"
    assert slots.destination == "FRA"


def test_mock_nlu_albanian_clarification_message() -> None:
    state = _state("pershendetje", language=Language.SQ)
    slots = MockNluExtractor().extract(state)
    message = clarification_message_for_slots(
        state,
        slots,
        settings=Settings(nlu_use_mock=True),
    )

    assert slots.needs_clarification is True
    assert "Ku" in message or "Nga" in message
    assert "TIA" not in message


def test_apply_travel_slots_updates_state() -> None:
    state = _state("ignored")
    slots = parse_travel_slots_payload(
        {
            "intent": "search_flights",
            "origin": "TIA",
            "destination": "FRA",
            "travel_date": "2025-09-15",
            "needs_clarification": False,
        }
    )

    apply_travel_slots(state, slots)

    assert state.flight_search.origin == "TIA"
    assert state.flight_search.destination == "FRA"
    assert state.flight_search.date == "2025-09-15"
    assert state.current_intent == "search_flights"


def test_llm_nlu_parses_structured_response() -> None:
    mock_client = MagicMock()
    mock_block = MagicMock(
        type="text",
        text=(
            '{"intent":"search_flights","origin":"TIA","destination":"FRA",'
            '"travel_date":"2025-09-15","needs_clarification":false,'
            '"clarification_message":null}'
        ),
    )
    mock_client.messages.create.return_value = MagicMock(content=[mock_block])

    extractor = LlmNluExtractor(
        settings=Settings(anthropic_api_key="test-key", nlu_use_mock=False),
        client=mock_client,
    )
    state = _state("I need to get from Tirana to Frankfurt mid September")

    slots = extractor.extract(state)

    assert slots.origin == "TIA"
    assert slots.destination == "FRA"
    assert slots.needs_clarification is False
    assert state.llm_call_count == 1
    mock_client.messages.create.assert_called_once()


def test_llm_nlu_asks_when_route_missing() -> None:
    mock_client = MagicMock()
    mock_block = MagicMock(
        type="text",
        text=(
            '{"intent":"greeting","origin":null,"destination":null,'
            '"travel_date":null,"needs_clarification":true,'
            '"clarification_message":"Where would you like to go?"}'
        ),
    )
    mock_client.messages.create.return_value = MagicMock(content=[mock_block])

    extractor = LlmNluExtractor(
        settings=Settings(anthropic_api_key="test-key", nlu_use_mock=False),
        client=mock_client,
    )
    slots = extractor.extract(_state("hello there"))

    assert slots.needs_clarification is True
    assert slots.clarification_message == "Where would you like to go?"


def test_get_nlu_extractor_uses_mock_by_default() -> None:
    extractor = get_nlu_extractor(settings=Settings(nlu_use_mock=True))

    assert isinstance(extractor, MockNluExtractor)


def test_get_nlu_extractor_requires_api_key_for_llm() -> None:
    with pytest.raises(NluError, match="ANTHROPIC_API_KEY"):
        get_nlu_extractor(settings=Settings(nlu_use_mock=False, anthropic_api_key=None))


def test_should_apply_nlu_clarification_when_route_missing() -> None:
    from app.agent.nlu import should_apply_nlu_clarification
    from app.agent.state import AgentState
    from app.models.nlu import TravelSlots

    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    slots = TravelSlots(intent="greeting", needs_clarification=False)

    assert should_apply_nlu_clarification(state, slots) is True


def test_extract_travel_slots_integration() -> None:
    state = _state("hi")
    slots = extract_travel_slots(state, settings=Settings(nlu_use_mock=True))

    assert slots.needs_clarification is True


def test_enrich_travel_slots_fills_partial_destination() -> None:
    state = _state("i want to go to tirana")
    generic = TravelSlots(needs_clarification=True)

    enriched = enrich_travel_slots(state, generic)

    assert enriched.destination == "TIA"
    assert enriched.origin is None
    assert enriched.needs_clarification is True


def test_clarification_prefers_partial_route_over_generic_llm_message() -> None:
    state = _state("i want to go to belgium")
    slots = TravelSlots(needs_clarification=True)

    message = clarification_message_for_slots(
        state,
        slots,
        settings=Settings(nlu_use_mock=True),
    )

    assert "Brussels" in message or "flying from" in message.lower()
    assert "TIA to FRA" not in message
    assert "2025-" not in message


def test_extract_travel_slots_partial_destination_tirana() -> None:
    state = _state("i want to go to tirana")
    slots = extract_travel_slots(state, settings=Settings(nlu_use_mock=True))

    assert slots.destination == "TIA"
    assert slots.needs_clarification is True
    message = clarification_message_for_slots(
        state,
        slots,
        settings=Settings(nlu_use_mock=True),
    )
    assert "TIA" not in message
    assert "flying from" in message.lower() or "Tirana" in message
