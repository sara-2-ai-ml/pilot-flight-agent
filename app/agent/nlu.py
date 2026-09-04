"""Natural language understanding — extract travel slots from user messages."""

from __future__ import annotations

import os
import re

from typing import Any, Protocol

import anthropic
from pydantic import ValidationError

from app.agent.conversation import is_complaint_intent
from app.agent.state import AgentState
from app.agent.travel_details import (
    apply_travel_detail_slots,
    parse_cabin_class,
    parse_passengers,
    parse_return_date,
    parse_time_of_day,
    parse_trip_type,
)
from app.config import Settings, get_settings
from app.core.tracing import trace_span
from app.models.nlu import TravelSlots
from app.models.planning import PlanStatus
from app.agent.planning import extract_json_object
from app.tools.flight_service import parse_route, parse_travel_date

NLU_SYSTEM_PROMPT = """You are the NLU module for Pilot Flight Agent, a flight concierge.
Return ONLY valid JSON. No markdown, no explanation.

Schema:
{
  "intent": "search_flights" | "book_flight" | "flight_status" | "greeting" | "other",
  "origin": "3-letter IATA code or null",
  "destination": "3-letter IATA code or null",
  "travel_date": "YYYY-MM-DD or null",
  "trip_type": "one_way" | "round_trip" | null,
  "return_date": "YYYY-MM-DD or null",
  "passengers": integer or null,
  "time_of_day": "morning" | "afternoon" | "evening" | null,
  "airline_preference": "2-letter airline code or null",
  "cabin_class": "economy" | "premium_economy" | "business" | "first" | null,
  "needs_clarification": boolean,
  "clarification_message": "string or null"
}

Rules:
- Extract structured slots only. Prefer null over guessing airport codes.
- Map cities/countries to IATA internally: Tirana→TIA, Frankfurt→FRA, Athens/Greece→ATH, Brussels/Belgium→BRU, etc.
- Set needs_clarification=true when route or date is missing for a travel request.
- clarification_message: optional short natural question in the user's language. NEVER include IATA codes or ISO dates in this field — use city/country names only. Prefer null; a separate conversational layer may phrase the reply.
"""

_GREETING_PREFIXES = (
    "hi",
    "hello",
    "hey",
    "pershendetje",
    "përshëndetje",
    "përshëndetje",
    "mirëdita",
    "miredita",
    "good morning",
    "good afternoon",
    "good evening",
)

_VAGUE_FLIGHT_HINTS = (
    "ticket",
    "tickets",
    "fluturim",
    "flight",
    "book",
    "rezervo",
    "rezervim",
    "dëshiroj",
    "desha",
    "dua",
    "want to go",
    "want to fly",
    "need a flight",
)

_CITY_TO_IATA = {
    "tirana": "TIA",
    "tiranë": "TIA",
    "tirane": "TIA",
    "frankfurt": "FRA",
    "munich": "MUC",
    "münchen": "MUC",
    "paris": "CDG",
    "france": "CDG",
    "new york": "JFK",
    "nyc": "JFK",
    "belgium": "BRU",
    "belgique": "BRU",
    "belgi": "BRU",
    "brussels": "BRU",
    "bruxelles": "BRU",
}

_VAGUE_DATE_HINTS = (
    "this month",
    "next month",
    "këtë muaj",
    "ketë muaj",
    "kete muaj",
)


class NluExtractor(Protocol):
    def extract(self, state: AgentState) -> TravelSlots:
        """Parse the current user message into structured travel slots."""


class NluError(Exception):
    """Raised when NLU cannot produce valid structured output."""


def _is_greeting(message: str) -> bool:
    lowered = message.lower().strip()
    if not lowered:
        return False
    for prefix in _GREETING_PREFIXES:
        if lowered == prefix or lowered.startswith(f"{prefix} ") or lowered.startswith(f"{prefix}!"):
            return True
    return False


def _is_vague_flight_request(message: str) -> bool:
    lowered = message.lower()
    return any(hint in lowered for hint in _VAGUE_FLIGHT_HINTS)


def _resolve_city_fragment(fragment: str) -> str | None:
    cleaned = fragment.strip(" .,!?:;")
    if not cleaned:
        return None
    if cleaned.upper() in {code for code in _CITY_TO_IATA.values()}:
        return cleaned.upper()
    return _CITY_TO_IATA.get(cleaned)


def _city_route_from_message(message: str) -> tuple[str | None, str | None]:
    """Resolve city names to IATA codes for mock/offline NLU."""
    origin, destination = _partial_route_from_message(message)
    return origin, destination


def _partial_route_from_message(message: str) -> tuple[str | None, str | None]:
    """Extract origin and/or destination from city names and natural phrasing."""
    origin, destination = parse_route(message)
    if origin and destination:
        return origin, destination

    lowered = message.lower()
    from_to = re.search(
        r"\bfrom\s+(.+?)\s+to\s+(.+?)(?:\s+on|\s+this|\s+next|\s*$|,|\.|!)",
        lowered,
    )
    if from_to:
        parsed_origin = _resolve_city_fragment(from_to.group(1))
        parsed_destination = _resolve_city_fragment(from_to.group(2))
        if parsed_origin and parsed_destination:
            return parsed_origin, parsed_destination

    for match in re.finditer(
        r"\b([a-z\u00c0-\u024f]+)\s+(?:to|-)\s+([a-z\u00c0-\u024f]+)"
        r"(?:\s+(?:this|next|on)\b|[,.]|$)",
        lowered,
    ):
        parsed_origin = _resolve_city_fragment(match.group(1).strip())
        parsed_destination = _resolve_city_fragment(match.group(2).strip())
        if parsed_origin and parsed_destination:
            return parsed_origin, parsed_destination

    go_to = re.search(
        r"\b(?:go|fly|travel|want to go)\s+to\s+(.+?)(?:\s+(?:this|next|on)\b|[,.]|$)",
        lowered,
    )
    if go_to:
        parsed_destination = _resolve_city_fragment(go_to.group(1).strip())
        if parsed_destination:
            return None, parsed_destination

    from_only = re.search(r"\bfrom\s+(.+?)(?:\s+to\b|[,.]|$)", lowered)
    if from_only:
        parsed_origin = _resolve_city_fragment(from_only.group(1).strip())
        if parsed_origin:
            return parsed_origin, None

    found: list[str] = []
    for city, code in sorted(_CITY_TO_IATA.items(), key=lambda item: len(item[0]), reverse=True):
        if city in lowered and code not in found:
            found.append(code)
    if len(found) >= 2:
        return found[0], found[1]
    if len(found) == 1:
        return None, found[0]
    return None, None


def mentions_vague_travel_date(message: str) -> bool:
    lowered = message.lower()
    return any(hint in lowered for hint in _VAGUE_DATE_HINTS)


def _infer_search_intent(message: str, *, current_intent: str | None = None) -> str:
    lowered = message.lower()
    if "book" in lowered or "rezervo" in lowered:
        return "book_flight"
    if re.search(r"\b(find|search|ticket|flight|fluturim)\b", lowered):
        return "search_flights"
    return current_intent or "search_flights"


def partial_route_clarification_message(
    state: AgentState,
    *,
    origin: str | None,
    destination: str | None,
) -> str:
    """Return a natural clarification prompt for a partial route."""
    from app.agent.conversational_prompts import generate_agent_message, infer_clarification_situation

    slots = TravelSlots(origin=origin, destination=destination, needs_clarification=True)
    situation = infer_clarification_situation(state, slots, origin=origin, destination=destination)
    return generate_agent_message(
        state,
        situation,
        origin=origin,
        destination=destination,
    )


def _resolved_route_from_slots(state: AgentState, slots: TravelSlots) -> tuple[str | None, str | None]:
    origin = slots.origin or state.flight_search.origin
    destination = slots.destination or state.flight_search.destination
    if origin and destination:
        return origin.upper(), destination.upper()

    parsed_origin, parsed_destination = _partial_route_from_message(state.user_message)
    origin = (slots.origin or parsed_origin or state.flight_search.origin or "").upper() or None
    destination = (
        slots.destination or parsed_destination or state.flight_search.destination or ""
    ).upper() or None
    return origin, destination


def route_change_requested(state: AgentState, slots: TravelSlots) -> bool:
    """Return True when the user is steering toward a different route than session state."""
    if is_complaint_intent(state.user_message):
        return False

    parsed_origin, parsed_destination = _partial_route_from_message(state.user_message)
    message_origin = (slots.origin or parsed_origin or "").upper() or None
    message_destination = (slots.destination or parsed_destination or "").upper() or None
    if not message_origin and not message_destination:
        return False

    origin, destination = message_origin or None, message_destination or None
    stored_origin = (state.flight_search.origin or "").upper()
    stored_destination = (state.flight_search.destination or "").upper()

    if destination and stored_destination and destination != stored_destination:
        return True
    if origin and stored_origin and origin != stored_origin:
        return True
    if origin and destination and state.flight_search.results:
        if origin != stored_origin or destination != stored_destination:
            return True
    return False


def route_clarification_needed(state: AgentState, slots: TravelSlots) -> bool:
    """Return True when the user still owes route or date details."""
    if slots.needs_clarification:
        return True

    origin, destination = _resolved_route_from_slots(state, slots)
    if origin and destination:
        if not slots.travel_date and not state.flight_search.date:
            if mentions_vague_travel_date(state.user_message):
                return True
        return False

    if origin or destination:
        return True

    if state.flight_search.destination and not state.flight_search.origin:
        return True
    if state.flight_search.origin and not state.flight_search.destination:
        return True
    return not slots.has_route


def prepare_route_update(state: AgentState, slots: TravelSlots) -> None:
    """Drop stale search results when the user changes route mid-conversation."""
    if not route_change_requested(state, slots):
        return

    from app.agent.conversation import reset_for_new_search

    parsed_origin, parsed_destination = _partial_route_from_message(state.user_message)
    new_origin = (slots.origin or parsed_origin or "").upper() or None
    new_destination = (slots.destination or parsed_destination or "").upper() or None

    reset_for_new_search(state)

    if new_destination and not new_origin:
        state.flight_search.origin = None
        state.flight_search.destination = new_destination
        state.flight_search.date = None
        if slots.travel_date or parse_travel_date(state.user_message):
            state.flight_search.date = slots.travel_date or parse_travel_date(state.user_message)
        return

    if new_origin:
        state.flight_search.origin = new_origin
    if new_destination:
        state.flight_search.destination = new_destination
    if not slots.travel_date and not parse_travel_date(state.user_message):
        state.flight_search.date = None


def should_apply_nlu_clarification(state: AgentState, slots: TravelSlots) -> bool:
    """Return True when NLU should pause the turn and ask the user for more input."""
    if is_complaint_intent(state.user_message):
        return False
    if state.user_context.get("awaiting"):
        return False

    needs_route = route_clarification_needed(state, slots)
    route_changed = route_change_requested(state, slots)

    if state.plan.steps and state.plan.status != PlanStatus.FAILED:
        if route_changed:
            return needs_route
        return False

    if state.flight_search.origin and state.flight_search.destination:
        if slots.travel_date or parse_travel_date(state.user_message):
            if mentions_vague_travel_date(state.user_message) and not slots.travel_date:
                return True
            return False
        if slots.trip_type or slots.return_date or slots.passengers is not None:
            return False
        if slots.time_of_day or slots.airline_preference or slots.cabin_class:
            return False
        if needs_route:
            return True
        return bool(slots.needs_clarification)
    if slots.needs_clarification:
        return True
    return not slots.has_route


def _should_update_intent(state: AgentState, reconciled_intent: str | None) -> bool:
    """Keep book intent on follow-up turns that only add dates or travel details."""
    if reconciled_intent is None:
        return False
    if reconciled_intent == "book_flight":
        return True
    if reconciled_intent == "search_flights":
        if re.search(r"\b(find|search)\b", state.user_message.lower()):
            return True
        return state.current_intent != "book_flight"
    return True


def enrich_travel_slots(state: AgentState, slots: TravelSlots) -> TravelSlots:
    """Merge heuristic city/route parsing into NLU output when slots are incomplete."""
    parsed_origin, parsed_destination = _partial_route_from_message(state.user_message)
    origin = (slots.origin or parsed_origin or "").upper() or None
    destination = (slots.destination or parsed_destination or "").upper() or None

    updates: dict[str, object] = {}
    if origin and origin != slots.origin:
        updates["origin"] = origin
    if destination and destination != slots.destination:
        updates["destination"] = destination

    merged = slots.model_copy(update=updates) if updates else slots

    if (merged.origin and not merged.destination) or (merged.destination and not merged.origin):
        return merged.model_copy(update={"needs_clarification": True, "clarification_message": None})

    if merged.origin and merged.destination and mentions_vague_travel_date(state.user_message):
        if not merged.travel_date:
            return merged.model_copy(update={"needs_clarification": True, "clarification_message": None})

    return merged


def clarification_message_for_slots(
    state: AgentState,
    slots: TravelSlots,
    *,
    settings: Settings | None = None,
) -> str:
    """Return the user-facing clarification prompt for the current NLU result."""
    from app.agent.conversational_prompts import resolve_clarification_message

    return resolve_clarification_message(state, slots, settings=settings)


def parse_travel_slots_payload(payload: dict[str, Any]) -> TravelSlots:
    """Validate NLU JSON against the TravelSlots model."""
    try:
        return TravelSlots.model_validate(payload)
    except ValidationError as exc:
        raise NluError("NLU JSON did not match TravelSlots schema.") from exc


def apply_travel_slots(state: AgentState, slots: TravelSlots) -> None:
    """Persist extracted slots on session state for downstream workers."""
    if slots.origin:
        state.flight_search.origin = slots.origin.upper()
    if slots.destination:
        state.flight_search.destination = slots.destination.upper()
    if slots.travel_date:
        state.flight_search.date = slots.travel_date
    if slots.intent:
        reconciled = reconcile_intent_with_message(state.user_message, slots.intent)
        if _should_update_intent(state, reconciled):
            state.current_intent = reconciled
    apply_travel_detail_slots(state, slots, message=state.user_message)


def reconcile_intent_with_message(message: str, intent: str | None) -> str | None:
    """Prefer explicit find/search vs book wording over a misclassified LLM intent."""
    lowered = message.lower()
    has_find = re.search(r"\b(find|search)\b", lowered) is not None
    has_book = re.search(r"\b(book|rezervo|rezervim)\b", lowered) is not None
    if has_find and not has_book:
        return "search_flights"
    if has_book:
        return "book_flight"
    return intent


class MockNluExtractor:
    """Heuristic NLU for tests and local development without an LLM API key."""

    def extract(self, state: AgentState) -> TravelSlots:
        message = state.user_message.strip()
        origin, destination = parse_route(message)
        travel_date = parse_travel_date(message)

        if origin is None or destination is None:
            city_origin, city_destination = _partial_route_from_message(message)
            origin = origin or city_origin
            destination = destination or city_destination

        if (origin and not destination) or (destination and not origin):
            return TravelSlots(
                intent=_infer_search_intent(message, current_intent=state.current_intent),
                origin=origin,
                destination=destination,
                travel_date=travel_date,
                needs_clarification=True,
            )

        if origin and destination and not travel_date and mentions_vague_travel_date(message):
            return TravelSlots(
                intent=_infer_search_intent(message, current_intent=state.current_intent),
                origin=origin,
                destination=destination,
                needs_clarification=True,
            )

        if travel_date and not origin and not destination:
            return TravelSlots(
                intent="book_flight" if state.current_intent == "book_flight" else "search_flights",
                travel_date=travel_date,
            )

        parsed_trip = parse_trip_type(message)
        parsed_return = parse_return_date(message)
        parsed_passengers = parse_passengers(message)
        parsed_time = parse_time_of_day(message)
        parsed_cabin = parse_cabin_class(message)
        if (
            not origin
            and not destination
            and any(
                value is not None
                for value in (
                    parsed_trip,
                    parsed_return,
                    parsed_passengers,
                    parsed_time,
                    parsed_cabin,
                )
            )
        ):
            return TravelSlots(
                intent="book_flight" if state.current_intent == "book_flight" else "search_flights",
                trip_type=parsed_trip,
                return_date=parsed_return,
                passengers=parsed_passengers,
                time_of_day=parsed_time,
                cabin_class=parsed_cabin,
            )

        if origin and destination:
            lowered = message.lower()
            intent = _infer_search_intent(message, current_intent=state.current_intent)
            return TravelSlots(
                intent=intent,
                origin=origin,
                destination=destination,
                travel_date=travel_date,
                trip_type=parse_trip_type(message),
                return_date=parse_return_date(message),
                passengers=parse_passengers(message),
                time_of_day=parse_time_of_day(message),
                cabin_class=parse_cabin_class(message),
            )

        if _is_vague_flight_request(message):
            if state.flight_search.destination and not state.flight_search.origin:
                return TravelSlots(
                    intent="search_flights",
                    destination=state.flight_search.destination,
                    needs_clarification=True,
                )
            if state.flight_search.origin and not state.flight_search.destination:
                return TravelSlots(
                    intent="search_flights",
                    origin=state.flight_search.origin,
                    needs_clarification=True,
                )

        if _is_greeting(message) or _is_vague_flight_request(message):
            return TravelSlots(
                intent="greeting" if _is_greeting(message) else "search_flights",
                needs_clarification=True,
            )

        return TravelSlots(needs_clarification=True)


class LlmNluExtractor:
    """Claude-backed NLU for production natural language understanding."""

    def __init__(
        self,
        settings: Settings,
        client: anthropic.Anthropic | None = None,
    ) -> None:
        if not settings.anthropic_api_key:
            raise NluError("ANTHROPIC_API_KEY is required for LLM NLU.")

        self._settings = settings
        self._client = client or anthropic.Anthropic(
            api_key=settings.anthropic_api_key,
            timeout=settings.external_llm_timeout_seconds,
        )

    def extract(self, state: AgentState) -> TravelSlots:
        user_prompt = (
            f"User message: {state.user_message}\n"
            f"Language hint: {state.language.value}\n"
            "Extract travel slots from this message."
        )

        try:
            response = self._client.messages.create(
                model=self._settings.anthropic_model,
                max_tokens=512,
                system=NLU_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
        except anthropic.APITimeoutError as exc:
            raise NluError(
                f"LLM NLU timed out after {self._settings.external_llm_timeout_seconds} seconds.",
            ) from exc
        except TimeoutError as exc:
            raise NluError(
                f"LLM NLU timed out after {self._settings.external_llm_timeout_seconds} seconds.",
            ) from exc

        text_blocks = [block.text for block in response.content if block.type == "text"]
        if not text_blocks:
            raise NluError("LLM NLU returned no text content.")

        usage = getattr(response, "usage", None)
        if usage is not None:
            state.token_usage += int(getattr(usage, "input_tokens", 0) or 0)
            state.token_usage += int(getattr(usage, "output_tokens", 0) or 0)

        state.llm_call_count += 1
        payload = extract_json_object(text_blocks[0])
        slots = parse_travel_slots_payload(payload)

        if slots.needs_clarification and slots.clarification_message:
            from app.agent.conversational_prompts import is_natural_clarification

            if not is_natural_clarification(slots.clarification_message):
                slots = slots.model_copy(update={"clarification_message": None})

        return slots


def get_nlu_extractor(
    *,
    settings: Settings | None = None,
    use_mock: bool | None = None,
) -> NluExtractor:
    """Return the configured NLU implementation."""
    resolved = settings or get_settings()
    mock = resolved.nlu_use_mock if use_mock is None else use_mock

    if mock:
        return MockNluExtractor()
    if not resolved.anthropic_api_key:
        raise NluError("ANTHROPIC_API_KEY is required when NLU_USE_MOCK=false.")

    return LlmNluExtractor(resolved)


def extract_travel_slots(
    state: AgentState,
    *,
    extractor: NluExtractor | None = None,
    settings: Settings | None = None,
) -> TravelSlots:
    """Run NLU on the current user turn."""
    resolved_extractor = extractor or get_nlu_extractor(settings=settings)
    with trace_span("nlu_extract", kind="nlu", message=state.user_message):
        slots = resolved_extractor.extract(state)
        return enrich_travel_slots(state, slots)
