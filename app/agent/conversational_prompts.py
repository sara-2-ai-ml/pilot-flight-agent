"""Natural, customer-facing agent messages — LLM-backed in production."""

from __future__ import annotations

import re
from typing import Any, Protocol

import anthropic

from app.agent.state import AgentState
from app.config import Settings, get_settings
from app.core.tracing import trace_span
from app.models.agent import Language
from app.models.nlu import TravelSlots

_IATA_TO_LABEL: dict[str, str] = {
    "TIA": "Tirana",
    "FRA": "Frankfurt",
    "MUC": "Munich",
    "CDG": "Paris",
    "JFK": "New York",
    "BRU": "Brussels",
    "ATH": "Athens",
    "SKG": "Thessaloniki",
}

_TECHNICAL_IATA = re.compile(
    r"\b(" + "|".join(_IATA_TO_LABEL.keys()) + r")\b",
    re.IGNORECASE,
)
_ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_TECHNICAL_HINT = re.compile(r"\b(e\.g\.|p\.sh\.|for example)\b", re.IGNORECASE)

CONVERSATIONAL_SYSTEM_PROMPT = """You are a warm, concise flight concierge chatting with a customer.
Write ONE short reply (1-3 sentences). Sound human, not like a form.

Rules:
- NEVER use IATA airport codes (TIA, FRA, ATH, etc.).
- NEVER use ISO date formats (YYYY-MM-DD).
- Use city and country names people understand.
- Ask only for information listed under "Still needed".
- Match the customer's language when a language hint is provided.
Return ONLY the reply text — no JSON, markdown, or bullet lists unless truly necessary."""


class ConversationalPromptGenerator(Protocol):
    def generate(
        self,
        state: AgentState,
        *,
        situation: str,
        origin: str | None = None,
        destination: str | None = None,
        route_label: str | None = None,
    ) -> str:
        """Return a natural customer-facing message."""


def place_label(code: str | None) -> str | None:
    """Map an internal IATA code to a human place name for customer messages."""
    if not code:
        return None
    upper = code.upper()
    return _IATA_TO_LABEL.get(upper, None)


def is_natural_clarification(text: str | None) -> bool:
    """Return True when text looks conversational rather than a technical form prompt."""
    if not text or not text.strip():
        return False
    if _ISO_DATE.search(text):
        return False
    if _TECHNICAL_HINT.search(text):
        return False
    if _TECHNICAL_IATA.search(text):
        return False
    return True


def infer_clarification_situation(
    state: AgentState,
    slots: TravelSlots,
    *,
    origin: str | None = None,
    destination: str | None = None,
) -> str:
    """Pick the conversational template key for the current clarification turn."""
    from app.agent.nlu import mentions_vague_travel_date

    resolved_origin = origin or slots.origin or state.flight_search.origin
    resolved_destination = destination or slots.destination or state.flight_search.destination

    if resolved_origin and resolved_destination and mentions_vague_travel_date(state.user_message):
        return "vague_date"
    if resolved_destination and not resolved_origin:
        return "missing_origin"
    if resolved_origin and not resolved_destination:
        return "missing_destination"
    if resolved_origin and resolved_destination and not (
        slots.travel_date or state.flight_search.date
    ):
        return "missing_date"
    if slots.intent == "greeting" or state.user_message.strip().lower() in {
        "hi",
        "hello",
        "hey",
        "pershendetje",
        "përshëndetje",
        "miredita",
        "mirëdita",
    }:
        return "greeting"
    return "missing_route"


class MockConversationalPromptGenerator:
    """Offline-friendly natural prompts for tests — no airport codes or ISO dates."""

    def generate(
        self,
        state: AgentState,
        *,
        situation: str,
        origin: str | None = None,
        destination: str | None = None,
        route_label: str | None = None,
    ) -> str:
        origin_name = place_label(origin) or "your departure city"
        destination_name = place_label(destination) or "your destination"
        sq = state.language == Language.SQ

        if situation == "greeting":
            return (
                "Përshëndetje! Nga po nisni dhe ku dëshironi të shkoni?"
                if sq
                else "Hello! Where are you flying from, and where would you like to go?"
            )
        if situation == "missing_origin":
            dest = destination_name if place_label(destination) else "there"
            return (
                f"Shkëlqyeshëm — drejt {dest}! Nga po nisni?"
                if sq
                else f"Great — heading to {dest}! Where will you be flying from?"
            )
        if situation == "missing_destination":
            origin_name = place_label(origin) or "your city"
            return (
                f"Nga {origin_name}, ku dëshironi të shkoni?"
                if sq
                else f"Flying from {origin_name} — where would you like to go?"
            )
        if situation == "missing_date":
            return (
                f"Mirë — {origin_name} drejt {destination_name}. Cila datë ju përshtatet?"
                if sq
                else f"Got it — {origin_name} to {destination_name}. When would you like to travel?"
            )
        if situation == "vague_date":
            return (
                "Cila ditë këtë muaj ju përshtatet më mirë?"
                if sq
                else "Which day this month works best for you?"
            )
        if situation == "complaint_recovery":
            return (
                "Më vjen keq për konfuzionin. Më thuaj ku dëshiron të shkosh dhe kur, "
                "që të fillojmë nga e para."
                if sq
                else "Sorry about the confusion. Tell me where you'd like to go and when, "
                "and we'll start fresh."
            )
        if situation == "travel_details":
            return (
                f"Mirë — {origin_name} drejt {destination_name}. "
                "A është vajtje e thjeshtë apo vajtje-ardhje, dhe sa persona udhëtojnë?"
                if sq
                else f"Got it — {origin_name} to {destination_name}. "
                "Will this be one-way or round-trip, and how many passengers?"
            )
        if situation == "preferences":
            return (
                "Ka ndonjë preferencë për kohën e ditës, kompaninë ajrore, ose klasën e udhëtimit?"
                if sq
                else "Any preferences on time of day, airline, or cabin class?"
            )
        if situation == "pricing_unavailable":
            label = route_label or f"{origin_name} to {destination_name}"
            return (
                f"Mund t'ju tregoj oraret e fluturimeve për {label}, "
                "por nuk kam çmime të besueshme. Dëshironi t'i shihni fluturimet sipas orarit?"
                if sq
                else f"I can show you flight schedules for {label}, but I don't have reliable fares. "
                "Would you like to see flights by schedule instead?"
            )
        if situation == "idle_ready":
            return (
                "Jam gati të ndihmoj. Çfarë dëshiron të bëjmë tani?"
                if sq
                else "I'm ready to help. What would you like to do next?"
            )
        return (
            "Ku dëshironi të fluturoni? Më tregoni nisjen dhe destinacionin."
            if sq
            else "Where are you flying from, and where would you like to go?"
        )


class LlmConversationalPromptGenerator:
    """Claude-backed natural phrasing for clarification and guidance messages."""

    def __init__(
        self,
        settings: Settings,
        client: anthropic.Anthropic | None = None,
    ) -> None:
        if not settings.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is required for LLM conversational prompts.")
        self._settings = settings
        self._client = client or anthropic.Anthropic(
            api_key=settings.anthropic_api_key,
            timeout=settings.external_llm_timeout_seconds,
        )
        self._fallback = MockConversationalPromptGenerator()

    def generate(
        self,
        state: AgentState,
        *,
        situation: str,
        origin: str | None = None,
        destination: str | None = None,
        route_label: str | None = None,
    ) -> str:
        origin_name = place_label(origin)
        destination_name = place_label(destination)
        still_needed = _still_needed_for_situation(situation)
        user_prompt = (
            f"Situation: {situation}\n"
            f"Customer message: {state.user_message}\n"
            f"Language hint: {state.language.value}\n"
            f"Known origin: {origin_name or origin or 'unknown'}\n"
            f"Known destination: {destination_name or destination or 'unknown'}\n"
            f"Route context: {route_label or 'none'}\n"
            f"Still needed from customer: {still_needed}\n"
            "Write the next concierge reply."
        )
        try:
            response = self._client.messages.create(
                model=self._settings.anthropic_model,
                max_tokens=220,
                system=CONVERSATIONAL_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
        except (anthropic.APITimeoutError, TimeoutError, anthropic.APIError):
            return self._fallback.generate(
                state,
                situation=situation,
                origin=origin,
                destination=destination,
                route_label=route_label,
            )

        text_blocks = [block.text for block in response.content if block.type == "text"]
        if not text_blocks:
            return self._fallback.generate(
                state,
                situation=situation,
                origin=origin,
                destination=destination,
                route_label=route_label,
            )

        usage = getattr(response, "usage", None)
        if usage is not None:
            state.token_usage += int(getattr(usage, "input_tokens", 0) or 0)
            state.token_usage += int(getattr(usage, "output_tokens", 0) or 0)
        state.llm_call_count += 1

        reply = text_blocks[0].strip()
        if is_natural_clarification(reply):
            return reply
        return self._fallback.generate(
            state,
            situation=situation,
            origin=origin,
            destination=destination,
            route_label=route_label,
        )


def _still_needed_for_situation(situation: str) -> str:
    mapping = {
        "greeting": "departure city, destination, and optionally travel date",
        "missing_route": "departure city and destination",
        "missing_origin": "departure city",
        "missing_destination": "destination",
        "missing_date": "travel date",
        "vague_date": "specific day this month",
        "complaint_recovery": "where they want to go and when",
        "travel_details": "one-way vs round-trip, passenger count, return date if round-trip",
        "preferences": "time of day, airline, cabin class (all optional)",
        "pricing_unavailable": "confirm whether to show flights by schedule instead of price",
        "idle_ready": "what they would like to do next",
    }
    return mapping.get(situation, "missing travel details")


def get_conversational_generator(
    *,
    settings: Settings | None = None,
) -> ConversationalPromptGenerator:
    resolved = settings or get_settings()
    if resolved.nlu_use_mock:
        return MockConversationalPromptGenerator()
    if not resolved.anthropic_api_key:
        return MockConversationalPromptGenerator()
    return LlmConversationalPromptGenerator(resolved)


def generate_agent_message(
    state: AgentState,
    situation: str,
    *,
    origin: str | None = None,
    destination: str | None = None,
    route_label: str | None = None,
    settings: Settings | None = None,
) -> str:
    """Generate a natural customer-facing message for the given situation."""
    generator = get_conversational_generator(settings=settings)
    with trace_span(
        "conversational_prompt",
        kind="llm",
        situation=situation,
        message=state.user_message,
    ):
        return generator.generate(
            state,
            situation=situation,
            origin=origin,
            destination=destination,
            route_label=route_label,
        )


def resolve_clarification_message(
    state: AgentState,
    slots: TravelSlots,
    *,
    settings: Settings | None = None,
) -> str:
    """Pick or generate the best natural clarification reply for this turn."""
    from app.agent.nlu import _resolved_route_from_slots

    origin, destination = _resolved_route_from_slots(state, slots)
    situation = infer_clarification_situation(
        state,
        slots,
        origin=origin,
        destination=destination,
    )

    if is_natural_clarification(slots.clarification_message):
        return slots.clarification_message or ""

    return generate_agent_message(
        state,
        situation,
        origin=origin,
        destination=destination,
        settings=settings,
    )
