"""Agent loop — load state, execute steps, evaluate, respond."""

import time

from app.agent.budget import AgentBudget
from app.agent.coordinator import (
    execute_step,
    mark_plan_failed,
    prepare_step_retry,
    select_current_step,
    set_stub_failures,
)
from app.agent.conversation import (
    clear_travel_route,
    empathetic_recovery_message,
    handle_idle_conversation,
    handle_turn_during_pending_approval,
    is_complaint_intent,
    pending_approval_guidance,
    reset_for_new_search,
    should_ask_for_travel_date,
    travel_date_prompt,
)
from app.agent.nlu import (
    NluError,
    apply_travel_slots,
    clarification_message_for_slots,
    extract_travel_slots,
    get_nlu_extractor,
    prepare_route_update,
    should_apply_nlu_clarification,
)
from app.agent.travel_details import (
    ensure_travel_defaults,
    handle_preferences_clarification,
    handle_travel_details_clarification,
)
from app.agent.planning import Planner, PlanningError, ensure_plan
from app.agent.replanning import replan_for_state, set_stub_replan
from app.agent.reflection import (
    evaluate_and_record,
    record_failure,
    set_stub_ask_user,
    set_stub_fail_evaluation,
)
from app.core.logging import get_logger
from app.core.cost import log_cost_tracking
from app.core.metrics import MetricsSnapshot, log_turn_metrics
from app.core.observability import elapsed_ms
from app.agent.state import (
    AgentState,
    InMemoryStateStore,
    create_state_for_turn,
    get_state_store,
    new_conversation_id,
    update_from_user_message,
)
from app.config import Settings, get_settings
from app.models.agent import EvaluationStatus

_BUDGET_EXCEEDED_MESSAGE = "Agent budget exceeded. Please start a new conversation."
_FAILURE_MESSAGE = "I couldn't complete your request. Please try again or start a new conversation."
_PLANNING_FAILURE_MESSAGE = (
    "I couldn't create a plan for this request. Please try rephrasing your message."
)
_NLU_FAILURE_MESSAGE = (
    "I couldn't understand your request right now. Please try again in a moment."
)
_logger = get_logger("agent.loop")
_DEFAULT_READY_MESSAGE = "I'm ready to help. What would you like to do next?"


def format_user_response(step_messages: list[str]) -> str:
    """Turn internal step messages into a user-facing reply."""
    visible = [message for message in step_messages if message]
    if not visible:
        return _DEFAULT_READY_MESSAGE
    if len(visible) == 1:
        return visible[0]
    return "\n\n".join(visible)


def _handle_retry(
    state: AgentState,
    step_id: str,
    max_step_retries: int,
) -> bool:
    """Track retry count. Returns True if the loop should retry the same step."""
    retries = state.step_retry_counts.get(step_id, 0) + 1
    state.step_retry_counts[step_id] = retries
    return retries < max_step_retries


def _execute_plan_until_pause(
    state: AgentState,
    budget: AgentBudget,
    base_response: str,
    *,
    max_step_retries: int,
    max_replan_attempts: int,
    planner: Planner | None = None,
    settings: Settings | None = None,
) -> str:
    """Execute plan steps while evaluator allows progress and budget permits."""
    step_messages: list[str] = []
    ask_message: str | None = None
    fail_message: str | None = None

    while True:
        if budget.is_exceeded(state):
            break

        step = select_current_step(state)
        if step is None:
            break

        message, _success = execute_step(state, step)
        step_messages.append(message)
        if state.pending_approval is not None:
            break

        evaluation = evaluate_and_record(state)

        if evaluation.status == EvaluationStatus.CONTINUE:
            state.step_retry_counts.pop(step.id, None)
            continue

        if evaluation.status == EvaluationStatus.RETRY:
            prepare_step_retry(state.plan.steps[state.plan.current_step])
            if _handle_retry(state, step.id, max_step_retries):
                continue

            failure = record_failure(
                state,
                issue=f"Step '{step.id}' exceeded max retries ({max_step_retries}).",
                message="I couldn't complete this step after several attempts.",
                step_id=step.id,
            )
            mark_plan_failed(state)
            fail_message = failure.message or _FAILURE_MESSAGE
            break

        if evaluation.status == EvaluationStatus.REPLAN:
            if state.replan_count >= max_replan_attempts:
                failure = record_failure(
                    state,
                    issue=f"Exceeded max replan attempts ({max_replan_attempts}).",
                    message="I couldn't find a workable plan after several adjustments.",
                    step_id=step.id,
                )
                mark_plan_failed(state)
                fail_message = failure.message or _FAILURE_MESSAGE
                break

            replan_for_state(state, planner=planner, settings=settings)
            step_messages.append("Replanned with updated strategy.")
            continue

        if evaluation.status == EvaluationStatus.ASK_USER:
            ask_message = evaluation.message or "I need more information to continue."
            state.pending_question = ask_message
            break

        if evaluation.status == EvaluationStatus.FAIL:
            mark_plan_failed(state)
            fail_message = evaluation.message or _FAILURE_MESSAGE
            break

        break

    if ask_message is not None:
        return ask_message

    if fail_message is not None:
        return fail_message

    return format_user_response(step_messages)


def run_chat(
    *,
    user_message: str,
    trace_id: str,
    conversation_id: str | None = None,
    settings: Settings | None = None,
    store: InMemoryStateStore | None = None,
    planner: Planner | None = None,
    stub_failures: dict[str, int] | None = None,
    stub_replan: list[str] | None = None,
    stub_ask_user: list[str] | None = None,
    stub_fail_evaluation: list[str] | None = None,
) -> tuple[AgentState, str]:
    """Load session state, apply one turn, persist, return response text.

    Callers from HTTP handlers must run ``run_inbound_chat_guards()`` first.
    Direct test calls may pass already-normalized input.
    """
    resolved_settings = settings or get_settings()
    from app.agent.workers import configure_worker_registry

    configure_worker_registry(resolved_settings)
    resolved_store = store or get_state_store()
    budget = AgentBudget.from_settings(resolved_settings)
    conv_id = conversation_id or new_conversation_id()

    state = resolved_store.get(conv_id)
    if state is None:
        state = create_state_for_turn(
            conversation_id=conv_id,
            trace_id=trace_id,
            user_message=user_message,
        )
    else:
        update_from_user_message(state, user_message=user_message, trace_id=trace_id)

    if stub_failures:
        set_stub_failures(state, stub_failures)
    if stub_replan:
        set_stub_replan(state, stub_replan)
    if stub_ask_user:
        set_stub_ask_user(state, stub_ask_user)
    if stub_fail_evaluation:
        set_stub_fail_evaluation(state, stub_fail_evaluation)

    metrics_snapshot = MetricsSnapshot(state)
    turn_started_at = time.perf_counter()

    if budget.is_exceeded(state):
        state.iteration_count += 1
        resolved_store.save(state)
        return state, _BUDGET_EXCEEDED_MESSAGE

    resolved_planner = planner or None
    nlu_extractor = get_nlu_extractor(settings=resolved_settings)
    try:
        slots = extract_travel_slots(
            state,
            extractor=nlu_extractor,
            settings=resolved_settings,
        )
    except NluError as exc:
        _logger.warning(
            "nlu_failed",
            extra={"trace_id": trace_id, "event": "nlu_failed", "issue": str(exc)},
        )
        state.iteration_count += 1
        resolved_store.save(state)
        log_turn_metrics(
            _logger,
            state=state,
            snapshot=metrics_snapshot,
            latency_ms=elapsed_ms(turn_started_at),
            trace_id=trace_id,
        )
        log_cost_tracking(_logger, state=state, trace_id=trace_id)
        return state, _NLU_FAILURE_MESSAGE

    if is_complaint_intent(user_message):
        reset_for_new_search(state)
        clear_travel_route(state)
        message = empathetic_recovery_message(state)
        state.pending_question = message
        state.iteration_count += 1
        resolved_store.save(state)
        log_turn_metrics(
            _logger,
            state=state,
            snapshot=metrics_snapshot,
            latency_ms=elapsed_ms(turn_started_at),
            trace_id=trace_id,
        )
        log_cost_tracking(_logger, state=state, trace_id=trace_id)
        return state, message

    prepare_route_update(state, slots)

    if should_apply_nlu_clarification(state, slots):
        apply_travel_slots(state, slots)
        message = clarification_message_for_slots(state, slots, settings=resolved_settings)
        state.pending_question = message
        state.iteration_count += 1
        resolved_store.save(state)
        log_turn_metrics(
            _logger,
            state=state,
            snapshot=metrics_snapshot,
            latency_ms=elapsed_ms(turn_started_at),
            trace_id=trace_id,
        )
        log_cost_tracking(_logger, state=state, trace_id=trace_id)
        return state, message

    if should_ask_for_travel_date(slots, user_message):
        apply_travel_slots(state, slots)
        message = travel_date_prompt(state)
        state.pending_question = message
        state.iteration_count += 1
        resolved_store.save(state)
        log_turn_metrics(
            _logger,
            state=state,
            snapshot=metrics_snapshot,
            latency_ms=elapsed_ms(turn_started_at),
            trace_id=trace_id,
        )
        log_cost_tracking(_logger, state=state, trace_id=trace_id)
        return state, message

    trip_details_reply = handle_travel_details_clarification(state, slots)
    if trip_details_reply is not None:
        apply_travel_slots(state, slots)
        state.pending_question = trip_details_reply
        state.iteration_count += 1
        resolved_store.save(state)
        log_turn_metrics(
            _logger,
            state=state,
            snapshot=metrics_snapshot,
            latency_ms=elapsed_ms(turn_started_at),
            trace_id=trace_id,
        )
        log_cost_tracking(_logger, state=state, trace_id=trace_id)
        return state, trip_details_reply

    preferences_reply = handle_preferences_clarification(state, slots)
    if preferences_reply is not None:
        apply_travel_slots(state, slots)
        state.pending_question = preferences_reply
        state.iteration_count += 1
        resolved_store.save(state)
        log_turn_metrics(
            _logger,
            state=state,
            snapshot=metrics_snapshot,
            latency_ms=elapsed_ms(turn_started_at),
            trace_id=trace_id,
        )
        log_cost_tracking(_logger, state=state, trace_id=trace_id)
        return state, preferences_reply

    approval_reply = handle_turn_during_pending_approval(state, slots)
    if approval_reply is not None:
        state.iteration_count += 1
        resolved_store.save(state)
        log_turn_metrics(
            _logger,
            state=state,
            snapshot=metrics_snapshot,
            latency_ms=elapsed_ms(turn_started_at),
            trace_id=trace_id,
        )
        log_cost_tracking(_logger, state=state, trace_id=trace_id)
        return state, approval_reply

    apply_travel_slots(state, slots)
    ensure_travel_defaults(state, slots, message=user_message)

    try:
        ensure_plan(state, planner=resolved_planner, settings=resolved_settings)
    except PlanningError as exc:
        _logger.warning(
            "planning_failed",
            extra={"trace_id": trace_id, "event": "planning_failed", "issue": str(exc)},
        )
        message = clarification_message_for_slots(state, slots, settings=resolved_settings)
        state.pending_question = message
        state.iteration_count += 1
        resolved_store.save(state)
        log_turn_metrics(
            _logger,
            state=state,
            snapshot=metrics_snapshot,
            latency_ms=elapsed_ms(turn_started_at),
            trace_id=trace_id,
        )
        log_cost_tracking(_logger, state=state, trace_id=trace_id)
        return state, message

    if not state.plan.steps:
        idle_reply = handle_idle_conversation(state, slots)
        message = idle_reply or clarification_message_for_slots(
            state,
            slots,
            settings=resolved_settings,
        )
        state.pending_question = message
        state.iteration_count += 1
        resolved_store.save(state)
        log_turn_metrics(
            _logger,
            state=state,
            snapshot=metrics_snapshot,
            latency_ms=elapsed_ms(turn_started_at),
            trace_id=trace_id,
        )
        log_cost_tracking(_logger, state=state, trace_id=trace_id)
        return state, message

    response = _execute_plan_until_pause(
        state,
        budget,
        f"Pilot received: {user_message}",
        max_step_retries=resolved_settings.max_step_retries,
        max_replan_attempts=resolved_settings.max_replan_attempts,
        planner=resolved_planner,
        settings=resolved_settings,
    )

    if response == _DEFAULT_READY_MESSAGE:
        idle_reply = handle_idle_conversation(state, slots)
        if idle_reply is not None:
            response = idle_reply
        elif state.pending_approval is not None:
            response = pending_approval_guidance(state)

    state.iteration_count += 1
    resolved_store.save(state)

    turn = log_turn_metrics(
        _logger,
        state=state,
        snapshot=metrics_snapshot,
        latency_ms=elapsed_ms(turn_started_at),
        trace_id=trace_id,
    )
    log_cost_tracking(_logger, state=state, trace_id=trace_id, turn=turn)

    return state, response
