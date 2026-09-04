"""Evaluator / reflection — CONTINUE, RETRY, REPLAN, ASK_USER, FAIL."""

from app.agent.planning import user_wants_booking
from app.agent.replanning import consume_stub_replan
from app.agent.state import AgentState
from app.core.errors import CIRCUIT_OPEN_USER_MESSAGE, is_clarification_error, is_terminal_worker_failure
from app.config import get_settings
from app.models.agent import EvaluationResult, EvaluationStatus, ReflectionRecord
from app.models.planning import PlanStep, StepStatus
from app.tools.flight_service import format_flight_results_message

_STUB_ASK_USER_KEY = "stub_ask_user_steps"
_STUB_FAIL_EVAL_KEY = "stub_fail_eval_steps"
_DEFAULT_FAIL_MESSAGE = "I couldn't complete your request. Please try again or start a new conversation."
_PRICE_INTENT_KEYWORDS = (
    "cheapest",
    "cheap",
    "lowest price",
    "best price",
    "fare",
    "price",
    "cost",
    " më lirë",
    "me te lire",
    "lirë",
    "cmim",
    "çmim",
)


def set_stub_fail_evaluation(state: AgentState, step_ids: list[str]) -> None:
    """Test hook — trigger terminal FAIL after the named steps succeed."""
    state.user_context[_STUB_FAIL_EVAL_KEY] = ",".join(step_ids)


def consume_stub_fail_evaluation(state: AgentState, step_id: str) -> bool:
    """Return True once when a stub fail trigger is configured for this step."""
    raw = state.user_context.get(_STUB_FAIL_EVAL_KEY, "")
    if not raw:
        return False

    pending = [entry for entry in raw.split(",") if entry]
    if step_id not in pending:
        return False

    pending.remove(step_id)
    if pending:
        state.user_context[_STUB_FAIL_EVAL_KEY] = ",".join(pending)
    else:
        state.user_context.pop(_STUB_FAIL_EVAL_KEY, None)

    return True


def set_stub_ask_user(state: AgentState, step_ids: list[str]) -> None:
    """Test hook — trigger ASK_USER after the named steps succeed."""
    state.user_context[_STUB_ASK_USER_KEY] = ",".join(step_ids)


def consume_stub_ask_user(state: AgentState, step_id: str) -> bool:
    """Return True once when a stub ask-user trigger is configured for this step."""
    raw = state.user_context.get(_STUB_ASK_USER_KEY, "")
    if not raw:
        return False

    pending = [entry for entry in raw.split(",") if entry]
    if step_id not in pending:
        return False

    pending.remove(step_id)
    if pending:
        state.user_context[_STUB_ASK_USER_KEY] = ",".join(pending)
    else:
        state.user_context.pop(_STUB_ASK_USER_KEY, None)

    return True


def user_requests_pricing(state: AgentState) -> bool:
    """Detect when the user asked for fares the public API cannot provide."""
    lowered = state.user_message.lower()
    return any(keyword in lowered for keyword in _PRICE_INTENT_KEYWORDS)


def evaluate_pricing_availability(state: AgentState, *, step: PlanStep) -> EvaluationResult | None:
    """Return ASK_USER when a pricing request cannot be satisfied."""
    if step.action != "search_flights" or not user_requests_pricing(state):
        return None

    from app.agent.conversational_prompts import generate_agent_message, place_label

    origin = state.flight_search.origin
    destination = state.flight_search.destination
    origin_label = place_label(origin) or "your origin"
    destination_label = place_label(destination) or "your destination"
    route_label = f"{origin_label} to {destination_label}"

    return EvaluationResult(
        status=EvaluationStatus.ASK_USER,
        issue="User requested fare comparison but pricing is unavailable.",
        message=generate_agent_message(
            state,
            "pricing_unavailable",
            origin=origin,
            destination=destination,
            route_label=route_label,
        ),
    )


def evaluate_search_completion(state: AgentState, *, step: PlanStep) -> EvaluationResult | None:
    """Pause after search so the user can pick a flight before booking."""
    if step.action != "search_flights" or user_wants_booking(state):
        return None
    if not state.flight_search.results:
        return None

    settings = get_settings()
    source = "mock" if settings.flight_api_use_mock else "live"
    return EvaluationResult(
        status=EvaluationStatus.ASK_USER,
        issue="Search completed; waiting for the user to choose a flight.",
        message=format_flight_results_message(state, source=source),
    )


def evaluate_step_result(
    state: AgentState,
    *,
    step: PlanStep,
    success: bool,
    output: str,
    error: str | None = None,
    error_code: str | None = None,
    user_message: str | None = None,
) -> EvaluationResult:
    """Evaluate the outcome of one executed plan step."""
    if success and step.status == StepStatus.COMPLETED:
        if consume_stub_replan(state, step.id):
            return EvaluationResult(
                status=EvaluationStatus.REPLAN,
                issue=f"Step '{step.id}' requires a new plan.",
                message="Adjusting the plan based on new information.",
            )
        if consume_stub_ask_user(state, step.id):
            return EvaluationResult(
                status=EvaluationStatus.ASK_USER,
                issue=f"Step '{step.id}' requires clarification from the user.",
                message="I need a bit more information before I can continue.",
            )
        if consume_stub_fail_evaluation(state, step.id):
            return EvaluationResult(
                status=EvaluationStatus.FAIL,
                issue=f"Step '{step.id}' cannot be completed.",
                message=_DEFAULT_FAIL_MESSAGE,
            )
        pricing_result = evaluate_pricing_availability(state, step=step)
        if pricing_result is not None:
            return pricing_result
        search_pause = evaluate_search_completion(state, step=step)
        if search_pause is not None:
            return search_pause
        return EvaluationResult(status=EvaluationStatus.CONTINUE)

    if error:
        if is_terminal_worker_failure(error_code):
            return EvaluationResult(
                status=EvaluationStatus.FAIL,
                issue=error,
                message=user_message or CIRCUIT_OPEN_USER_MESSAGE,
            )
        if is_clarification_error(error_code):
            return EvaluationResult(
                status=EvaluationStatus.ASK_USER,
                issue=error,
                message=user_message
                or "I need a bit more information before I can continue.",
            )
        return EvaluationResult(
            status=EvaluationStatus.RETRY,
            issue=error,
            message="Something went wrong while executing the plan step. Retrying may help.",
        )

    return EvaluationResult(
        status=EvaluationStatus.FAIL,
        issue=f"Step '{step.id}' did not complete successfully.",
        message="I couldn't complete that step.",
    )


def evaluate_latest_tool_result(state: AgentState) -> EvaluationResult:
    """Evaluate the most recent tool call recorded on state."""
    if not state.tool_history:
        return EvaluationResult(
            status=EvaluationStatus.FAIL,
            issue="No tool result available for evaluation.",
            message=_DEFAULT_FAIL_MESSAGE,
        )

    last = state.tool_history[-1]
    current_step = state.plan.steps[state.plan.current_step]

    if last.status == StepStatus.COMPLETED.value:
        return evaluate_step_result(
            state,
            step=current_step,
            success=True,
            output=last.action,
        )

    return evaluate_step_result(
        state,
        step=current_step,
        success=False,
        output="",
        error=f"Tool {last.tool}.{last.action} failed.",
        error_code=last.error_code,
        user_message=last.message,
    )


def record_reflection(
    state: AgentState,
    result: EvaluationResult,
    *,
    step_id: str | None = None,
) -> ReflectionRecord:
    """Append evaluator output to session history."""
    resolved_step_id = step_id
    if resolved_step_id is None and state.plan.steps:
        resolved_step_id = state.plan.steps[state.plan.current_step].id

    record = ReflectionRecord(
        status=result.status,
        issue=result.issue,
        message=result.message,
        step_id=resolved_step_id,
        trace_id=state.trace_id,
        iteration=state.iteration_count,
    )
    state.reflection_history.append(record)
    return record


def record_failure(
    state: AgentState,
    *,
    issue: str,
    message: str | None = None,
    step_id: str | None = None,
) -> EvaluationResult:
    """Record a terminal failure after evaluation."""
    result = EvaluationResult(status=EvaluationStatus.FAIL, issue=issue, message=message)
    record_reflection(state, result, step_id=step_id)
    return result


def evaluate_and_record(state: AgentState) -> EvaluationResult:
    """Evaluate the latest tool result and persist the decision."""
    result = evaluate_latest_tool_result(state)
    record_reflection(state, result)
    return result
