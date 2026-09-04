"""Structured planning — LLM produces JSON plan, not free text."""

import json
import re
from typing import Any, Protocol

import anthropic
from pydantic import ValidationError

from app.agent.state import AgentState
from app.config import Settings, get_settings
from app.core.tracing import trace_span
from app.models.planning import Plan, PlanStatus, PlanStep, Worker
from app.tools.flight_service import parse_flight_number, parse_route

PLANNER_SYSTEM_PROMPT = """You are the planning module for Pilot Flight Agent.
Return ONLY valid JSON for a Plan object. No markdown, no explanation.

Schema:
{
  "goal": "string",
  "steps": [
    {
      "id": "string",
      "worker": "flight" | "booking",
      "action": "string",
      "depends_on": ["step_id"]
    }
  ]
}

Rules:
- action MUST be exactly one of: search_flights, validate_options, create_booking
- NEVER use natural-language descriptions as action values
- Use worker "flight" for search_flights and validate_options
- Use worker "booking" for create_booking
- If the user only greets or did not provide origin and destination, return:
  {"goal":"Clarify travel request","steps":[]}
- Step ids must be unique
- depends_on must reference earlier step ids
- Prefer plans with 1-4 steps
- If the user says "find", "search", or "show flights" WITHOUT asking to book, return ONLY:
  {"goal":"...","steps":[{"id":"search","worker":"flight","action":"search_flights","depends_on":[]}]}
- Include validate_options and create_booking ONLY when the user explicitly asks to book or reserve
"""


class PlanningError(Exception):
    """Raised when a planner cannot produce a valid plan."""


class Planner(Protocol):
    def create_plan(self, state: AgentState) -> Plan:
        """Build a structured plan for the current agent state."""


def build_default_flight_plan(goal: str) -> Plan:
    """Standard search → validate → booking plan used by mock/dev planners."""
    return Plan(
        goal=goal,
        steps=[
            PlanStep(id="search", worker=Worker.FLIGHT, action="search_flights"),
            PlanStep(
                id="select",
                worker=Worker.FLIGHT,
                action="validate_options",
                depends_on=["search"],
            ),
            PlanStep(
                id="booking",
                worker=Worker.BOOKING,
                action="create_booking",
                depends_on=["select"],
            ),
        ],
    )


def build_search_only_plan(goal: str) -> Plan:
    """Search flights and pause for the user to pick an option."""
    return Plan(
        goal=goal,
        steps=[PlanStep(id="search", worker=Worker.FLIGHT, action="search_flights")],
    )


def build_select_and_book_plan(goal: str) -> Plan:
    """Select from existing results and proceed to booking."""
    return Plan(
        goal=goal,
        steps=[
            PlanStep(id="select", worker=Worker.FLIGHT, action="validate_options"),
            PlanStep(
                id="booking",
                worker=Worker.BOOKING,
                action="create_booking",
                depends_on=["select"],
            ),
        ],
    )


_BOOK_HINTS = (
    "book",
    "rezervo",
    "rezervim",
    "beje book",
    "pay & book",
    "pay and book",
)


def _contains_word_hint(text: str, hint: str) -> bool:
    if " " in hint:
        return hint in text
    return re.search(rf"\b{re.escape(hint)}\b", text) is not None


def user_wants_search_only(state: AgentState) -> bool:
    """Return True when the user is browsing flights, not booking."""
    lowered = state.user_message.lower()
    has_find = _contains_word_hint(lowered, "find") or _contains_word_hint(lowered, "search")
    has_book = any(_contains_word_hint(lowered, hint) for hint in _BOOK_HINTS)
    if has_find and not has_book:
        return True
    if state.current_intent == "search_flights":
        return True
    return False


def _message_has_booking_follow_up(message: str) -> bool:
    """Detect follow-up turns that continue an in-progress booking conversation."""
    from app.agent.travel_details import (
        parse_cabin_class,
        parse_passengers,
        parse_return_date,
        parse_time_of_day,
        parse_trip_type,
    )
    from app.tools.flight_service import parse_travel_date

    if parse_travel_date(message):
        return True
    if parse_route(message)[0]:
        return True
    return any(
        parser(message)
        for parser in (
            parse_trip_type,
            parse_return_date,
            parse_passengers,
            parse_time_of_day,
            parse_cabin_class,
        )
    )


def user_wants_booking(state: AgentState) -> bool:
    """Return True when the user intent is to book, not just browse flights."""
    if user_wants_search_only(state):
        return False
    if _user_selecting_flight(state):
        return True
    if state.user_context.get("awaiting"):
        return True

    lowered = state.user_message.lower()
    if any(_contains_word_hint(lowered, hint) for hint in _BOOK_HINTS):
        return True

    if state.current_intent == "book_flight" and _message_has_booking_follow_up(state.user_message):
        return True

    return False


def _should_skip_new_plan(state: AgentState) -> bool:
    """Avoid auto-starting a new flight search on small talk or status follow-ups."""
    origin = state.flight_search.origin
    destination = state.flight_search.destination
    if (origin and not destination) or (destination and not origin):
        return True
    if _is_schedule_follow_up(state):
        return False
    if user_wants_booking(state) or _user_selecting_flight(state):
        return False

    lowered = state.user_message.lower()
    flight_hints = ("flight", "fluturim", "find", "search", "ticket", "rezervo")
    if any(_contains_word_hint(lowered, hint) for hint in flight_hints):
        return False
    if re.search(r"\bbook\b", lowered):
        return False

    return bool(state.booking.booking_id or state.flight_search.results)


def _user_selecting_flight(state: AgentState) -> bool:
    """Return True when the user is choosing from existing search results."""
    if parse_flight_number(state.user_message):
        return True

    lowered = state.user_message.lower()
    selection_hints = (
        "first option",
        "first one",
        "first flight",
        "pick the first",
        "choose the first",
        "option 1",
        "e para",
        "e parën",
    )
    return any(hint in lowered for hint in selection_hints)


def _is_schedule_follow_up(state: AgentState) -> bool:
    """Return True when the user accepts a schedule-only search after a pricing ask."""
    lowered = state.user_message.lower()
    if "schedule" not in lowered and "flights by" not in lowered:
        return False
    if not any(hint in lowered for hint in ("yes", "show", "schedule", "please", "ok", "sure")):
        return False

    return any(
        record.issue and "pricing" in record.issue.lower()
        for record in state.reflection_history
    )


def build_plan_for_state(state: AgentState, goal: str) -> Plan:
    """Pick a plan shape based on intent and whether search results already exist."""
    origin = state.flight_search.origin
    destination = state.flight_search.destination
    if not origin or not destination:
        parsed_origin, parsed_destination = parse_route(state.user_message)
        origin = origin or parsed_origin
        destination = destination or parsed_destination

    if state.flight_search.results and (
        user_wants_booking(state) or _user_selecting_flight(state)
    ):
        return build_select_and_book_plan(goal)

    if user_wants_booking(state):
        if origin and destination:
            return build_default_flight_plan(goal)
    return build_search_only_plan(goal)


def extract_json_object(text: str) -> dict[str, Any]:
    """Parse a JSON object from raw LLM output."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)

    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise PlanningError("Planner returned invalid JSON.") from exc

    if not isinstance(payload, dict):
        raise PlanningError("Planner JSON must be an object.")

    return payload


def parse_plan_payload(payload: dict[str, Any]) -> Plan:
    """Validate planner JSON against the Plan model."""
    try:
        plan = Plan.model_validate(payload)
    except ValidationError as exc:
        raise PlanningError("Planner JSON did not match Plan schema.") from exc
    validate_plan_actions(plan)
    return plan


_ALLOWED_WORKER_ACTIONS: dict[Worker, frozenset[str]] = {
    Worker.FLIGHT: frozenset({"search_flights", "validate_options", "get_flight_status"}),
    Worker.BOOKING: frozenset({"create_booking"}),
}


def validate_plan_actions(plan: Plan) -> None:
    """Reject planner output that references unsupported worker actions."""
    for step in plan.steps:
        allowed = _ALLOWED_WORKER_ACTIONS.get(step.worker)
        if allowed is None or step.action not in allowed:
            raise PlanningError(
                f"Unsupported action '{step.action}' for worker '{step.worker.value}'.",
            )


class MockPlanner:
    """Deterministic planner for tests and local development."""

    def create_plan(self, state: AgentState) -> Plan:
        goal = state.user_message.strip() or "Assist the user with flight booking"
        return build_plan_for_state(state, goal)


class LlmPlanner:
    """Claude-backed planner that returns structured JSON plans."""

    def __init__(
        self,
        settings: Settings,
        client: anthropic.Anthropic | None = None,
    ) -> None:
        if not settings.anthropic_api_key:
            raise PlanningError("ANTHROPIC_API_KEY is required for LLM planning.")

        self._settings = settings
        self._client = client or anthropic.Anthropic(
            api_key=settings.anthropic_api_key,
            timeout=settings.external_llm_timeout_seconds,
        )

    def create_plan(self, state: AgentState) -> Plan:
        user_prompt = (
            f"User message: {state.user_message}\n"
            f"Language hint: {state.language.value}\n"
            "Create the best plan for this request."
        )

        try:
            response = self._client.messages.create(
                model=self._settings.anthropic_model,
                max_tokens=1024,
                system=PLANNER_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
        except anthropic.APITimeoutError as exc:
            raise PlanningError(
                f"LLM planner timed out after {self._settings.external_llm_timeout_seconds} seconds.",
            ) from exc
        except TimeoutError as exc:
            raise PlanningError(
                f"LLM planner timed out after {self._settings.external_llm_timeout_seconds} seconds.",
            ) from exc

        text_blocks = [block.text for block in response.content if block.type == "text"]
        if not text_blocks:
            raise PlanningError("Planner returned no text content.")

        usage = getattr(response, "usage", None)
        if usage is not None:
            state.token_usage += int(getattr(usage, "input_tokens", 0) or 0)
            state.token_usage += int(getattr(usage, "output_tokens", 0) or 0)

        payload = extract_json_object(text_blocks[0])
        return parse_plan_payload(payload)


def get_planner(
    *,
    settings: Settings | None = None,
    use_mock: bool | None = None,
) -> Planner:
    """Return the configured planner implementation."""
    resolved = settings or get_settings()
    mock = resolved.planner_use_mock if use_mock is None else use_mock

    if mock:
        return MockPlanner()
    if not resolved.anthropic_api_key:
        raise PlanningError("ANTHROPIC_API_KEY is required when PLANNER_USE_MOCK=false.")

    return LlmPlanner(resolved)


def assign_plan_to_state(state: AgentState, plan: Plan) -> None:
    """Persist a validated plan on agent state."""
    state.plan = plan.model_copy(deep=True)
    state.plan.current_step = 0
    state.plan.status = PlanStatus.PENDING


def expand_route_plan_to_booking(state: AgentState, plan: Plan) -> Plan:
    """Upgrade search-only LLM plans to full booking when the user asked to book."""
    if not user_wants_booking(state):
        return plan

    origin = state.flight_search.origin
    destination = state.flight_search.destination
    if not origin or not destination:
        return plan

    actions = {step.action for step in plan.steps}
    if "create_booking" in actions:
        return plan

    if state.flight_search.results and actions <= {"search_flights", "validate_options"}:
        goal = (plan.goal or state.user_message).strip() or "Book flight"
        return build_select_and_book_plan(goal)

    if actions == {"search_flights"}:
        goal = (plan.goal or state.user_message).strip() or "Book flight"
        return build_default_flight_plan(goal)

    return plan


def coerce_plan_for_intent(state: AgentState, plan: Plan) -> Plan:
    """Normalize LLM plans so search requests never auto-select or auto-book."""
    if user_wants_booking(state) or _user_selecting_flight(state):
        actions = {step.action for step in plan.steps}
        goal = (plan.goal or state.user_message).strip() or "Book flight"
        if state.flight_search.results:
            return build_select_and_book_plan(goal)
        if "search_flights" in actions and "create_booking" not in actions:
            return build_default_flight_plan(goal)
        return plan

    if not plan.steps:
        return plan

    actions = {step.action for step in plan.steps}
    if "search_flights" in actions:
        goal = (plan.goal or state.user_message).strip() or "Find flights"
        return build_search_only_plan(goal)

    return plan


def ensure_plan(
    state: AgentState,
    *,
    planner: Planner | None = None,
    settings: Settings | None = None,
) -> None:
    """Create and attach a plan when the session has none yet."""
    if state.plan.status == PlanStatus.FAILED:
        state.plan = Plan()
        state.step_retry_counts.clear()
    elif state.plan.status == PlanStatus.COMPLETED:
        if _should_skip_new_plan(state):
            return
        state.plan = Plan()
        state.step_retry_counts.clear()
    elif state.plan.steps and state.plan.status == PlanStatus.IN_PROGRESS:
        return
    elif state.plan.steps and state.plan.status == PlanStatus.PENDING:
        return

    if _should_skip_new_plan(state):
        return

    resolved_settings = settings or get_settings()
    resolved_planner = planner or get_planner(settings=resolved_settings)
    with trace_span("create_plan", kind="plan", goal=state.user_message):
        plan = resolved_planner.create_plan(state)
        plan = expand_route_plan_to_booking(state, plan)
        plan = coerce_plan_for_intent(state, plan)
    assign_plan_to_state(state, plan)

    if isinstance(resolved_planner, LlmPlanner):
        state.llm_call_count += 1

