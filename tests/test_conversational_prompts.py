"""Natural conversational prompt tests."""

from app.agent.conversational_prompts import (
    MockConversationalPromptGenerator,
    is_natural_clarification,
    resolve_clarification_message,
)
from app.agent.nlu import MockNluExtractor, clarification_message_for_slots, extract_travel_slots
from app.agent.state import AgentState
from app.config import Settings
from app.models.agent import Language
from app.models.nlu import TravelSlots


def _state(message: str, *, language: Language = Language.EN) -> AgentState:
    state = AgentState.new(conversation_id="conv1", trace_id="trace1")
    state.user_message = message
    state.language = language
    return state


def test_is_natural_clarification_rejects_technical_examples() -> None:
    assert is_natural_clarification("Where would you like to go? (e.g. TIA to FRA)") is False
    assert is_natural_clarification("When do you want to travel on 2025-09-15?") is False
    assert is_natural_clarification("Where are you flying from?") is True


def test_mock_generator_avoids_airport_codes_and_iso_dates() -> None:
    generator = MockConversationalPromptGenerator()
    state = _state("hi")

    message = generator.generate(state, situation="greeting")
    assert "TIA" not in message
    assert "2025-" not in message
    assert "flying from" in message.lower()

    partial = generator.generate(
        state,
        situation="missing_origin",
        destination="BRU",
    )
    assert "TIA" not in partial
    assert "Brussels" in partial or "there" in partial.lower()


def test_clarification_message_for_slots_uses_natural_mock_copy() -> None:
    state = _state("hi")
    slots = MockNluExtractor().extract(state)

    message = clarification_message_for_slots(
        state,
        slots,
        settings=Settings(nlu_use_mock=True),
    )

    assert "TIA" not in message
    assert "2025-" not in message
    assert "flying from" in message.lower() or "Where" in message


def test_partial_destination_tirana_prompt_is_natural() -> None:
    state = _state("i want to go to tirana")
    slots = extract_travel_slots(state, settings=Settings(nlu_use_mock=True))

    message = clarification_message_for_slots(
        state,
        slots,
        settings=Settings(nlu_use_mock=True),
    )

    assert slots.destination == "TIA"
    assert "TIA" not in message
    assert "flying from" in message.lower() or "Tirana" in message


def test_resolve_clarification_keeps_natural_llm_nlu_message() -> None:
    state = _state("i want to go to greece")
    slots = TravelSlots(
        needs_clarification=True,
        clarification_message="Which city in Greece would you like to visit?",
    )

    message = resolve_clarification_message(
        state,
        slots,
        settings=Settings(nlu_use_mock=True),
    )

    assert message == "Which city in Greece would you like to visit?"
