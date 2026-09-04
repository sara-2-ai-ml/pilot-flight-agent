"""Conversational handling — context-aware replies outside the rigid plan loop."""

from __future__ import annotations

import re

from app.agent.approval_flow import cancel_pending_approval
from app.agent.state import AgentState
from app.guardrails.approval import format_approval_message
from app.models.agent import Language
from app.models.booking import BookingState
from app.models.nlu import TravelSlots
from app.models.planning import Plan

_CONFIRM_HINTS = (
    "confirm",
    "yes",
    "ok",
    "okay",
    "book it",
    "go ahead",
    "po",
    "konfirmo",
    "vazhdo",
)
_CANCEL_HINTS = (
    "cancel",
    "abort",
    "stop",
    "never mind",
    "nevermind",
    "anulo",
    "ndalo",
    "mos e rezervo",
)
_DATE_HINTS = (
    "date",
    "datë",
    "data",
    "when",
    "kur",
    "choose date",
    "pick date",
    "change date",
    "travel on",
    "on which day",
)
_COMPLAINT_HINTS = (
    "wrong",
    "mistake",
    "gabim",
    "ke gabuar",
    "things wrong",
    "not right",
    "incorrect",
)


def _lowered(message: str) -> str:
    return message.strip().lower()


def _contains_hint(text: str, hint: str) -> bool:
    if " " in hint:
        return hint in text
    return re.search(rf"\b{re.escape(hint)}\b", text) is not None


def is_confirm_intent(message: str) -> bool:
    text = _lowered(message)
    return any(_contains_hint(text, hint) for hint in _CONFIRM_HINTS)


def is_cancel_intent(message: str) -> bool:
    text = _lowered(message)
    return any(_contains_hint(text, hint) for hint in _CANCEL_HINTS)


def is_date_change_intent(message: str) -> bool:
    text = _lowered(message)
    return any(_contains_hint(text, hint) for hint in _DATE_HINTS)


def is_complaint_intent(message: str) -> bool:
    text = _lowered(message)
    return any(_contains_hint(text, hint) for hint in _COMPLAINT_HINTS)


def should_ask_for_travel_date(slots: TravelSlots, message: str) -> bool:
    """Ask for a date before booking when the user wants to book but gave no date."""
    if not slots.has_route or slots.travel_date:
        return False
    if slots.intent == "book_flight":
        return True
    lowered = _lowered(message)
    return "book" in lowered or "rezervo" in lowered


def travel_date_prompt(state: AgentState) -> str:
    from app.agent.conversational_prompts import generate_agent_message

    return generate_agent_message(
        state,
        "missing_date",
        origin=state.flight_search.origin,
        destination=state.flight_search.destination,
    )


def pending_approval_guidance(state: AgentState) -> str:
    if state.pending_approval is None:
        return "I'm ready to help. What would you like to do next?"

    approval_text = format_approval_message(state.pending_approval)
    if state.language == Language.SQ:
        suffix = (
            " Mund të shtypni **Pay & book** për të vazhduar, **Cancel** për ta anuluar, "
            "ose më thoni datën e re nëse dëshironi ta ndryshoni."
        )
    else:
        suffix = (
            " Tap **Pay & book** to proceed, **Cancel** to abort, "
            "or tell me a new travel date if you'd like to change it."
        )
    return f"{approval_text}\n\n{suffix}"


def empathetic_recovery_message(state: AgentState) -> str:
    from app.agent.conversational_prompts import generate_agent_message

    return generate_agent_message(state, "complaint_recovery")


def clear_travel_route(state: AgentState) -> None:
    """Clear stored route fields so the user can start a fresh search."""
    state.flight_search.origin = None
    state.flight_search.destination = None
    state.flight_search.date = None


def reset_for_new_search(state: AgentState) -> None:
    """Clear an in-flight booking hold so a new search can run."""
    state.pending_approval = None
    state.plan = Plan()
    state.step_retry_counts.clear()
    state.booking = BookingState()
    state.flight_search.results = []
    state.flight_search.return_results = []
    state.flight_search.selected_option_id = None
    state.flight_search.trip_type = None
    state.flight_search.return_date = None
    state.flight_search.passengers = 1
    state.flight_search.time_of_day = None
    state.flight_search.airline_preference = None
    state.flight_search.cabin_class = None
    state.flight_search.trip_details_asked = False
    state.flight_search.preferences_asked = False
    state.user_context.pop("awaiting", None)


def handle_turn_during_pending_approval(
    state: AgentState,
    slots: TravelSlots,
) -> str | None:
    """Handle natural-language turns while a booking approval is waiting."""
    if state.pending_approval is None:
        return None

    message = state.user_message.strip()
    if not message:
        return pending_approval_guidance(state)

    if is_confirm_intent(message):
        if state.language == Language.SQ:
            return (
                "Rezervimi është gati. Shtyp **Pay & book** poshtë "
                "për të vendosur kartën dhe përfunduar rezervimin."
            )
        return (
            "Your booking is ready. Tap **Pay & book** below "
            "to enter payment details and complete the reservation."
        )

    if is_cancel_intent(message):
        _, _ = cancel_pending_approval(state)
        if state.language == Language.SQ:
            return "E anulova kërkesën e rezervimit. Si mund të të ndihmoj tani?"
        return "I've cancelled the booking request. How can I help you now?"

    if slots.travel_date:
        reset_for_new_search(state)
        return None

    if is_date_change_intent(message):
        reset_for_new_search(state)
        return travel_date_prompt(state)

    if is_complaint_intent(message) or slots.intent == "other":
        reset_for_new_search(state)
        clear_travel_route(state)
        return empathetic_recovery_message(state)

    return pending_approval_guidance(state)


def handle_idle_conversation(state: AgentState, slots: TravelSlots) -> str | None:
    """Reply naturally when there is no executable plan step for this turn."""
    message = state.user_message.strip()
    if not message:
        return None

    if is_complaint_intent(message) or slots.intent == "other":
        reset_for_new_search(state)
        clear_travel_route(state)
        return empathetic_recovery_message(state)

    if is_greeting_only(message):
        from app.agent.conversational_prompts import generate_agent_message

        return generate_agent_message(state, "greeting")

    if state.flight_search.destination and not state.flight_search.origin:
        from app.agent.conversational_prompts import generate_agent_message

        return generate_agent_message(
            state,
            "missing_origin",
            destination=state.flight_search.destination,
        )

    if state.flight_search.origin and not state.flight_search.destination:
        from app.agent.conversational_prompts import generate_agent_message

        return generate_agent_message(
            state,
            "missing_destination",
            origin=state.flight_search.origin,
        )

    if state.flight_search.origin and state.flight_search.destination and not state.flight_search.date:
        return travel_date_prompt(state)

    if state.flight_search.results or state.booking.booking_id:
        from app.agent.conversational_prompts import generate_agent_message

        return generate_agent_message(state, "idle_ready")

    return None


def is_greeting_only(message: str) -> bool:
    text = _lowered(message)
    return text in {"hi", "hello", "hey", "pershendetje", "përshëndetje", "miredita", "mirëdita"}


def normalize_travel_date_value(raw: str) -> str | None:
    """Normalize common date strings to YYYY-MM-DD when possible."""
    cleaned = raw.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", cleaned):
        return cleaned

    space_match = re.search(r"\b(\d{4})\s+(\d{1,2})\s+(\d{1,2})\b", cleaned)
    if space_match:
        year, month, day = space_match.groups()
        return f"{year}-{int(month):02d}-{int(day):02d}"

    slash_match = re.search(r"\b(\d{4})/(\d{1,2})/(\d{1,2})\b", cleaned)
    if slash_match:
        year, month, day = slash_match.groups()
        return f"{year}-{int(month):02d}-{int(day):02d}"

    return None
