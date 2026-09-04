"""Human approval confirm/cancel flow — Phase 7.4."""

from __future__ import annotations

from app.agent.coordinator import execute_approved_step
from app.agent.state import AgentState, InMemoryStateStore, get_state_store
from app.agent.tool_history import record_tool_call
from app.config import Settings, get_settings
from app.guardrails.approval import APPROVAL_CANCELLED_STATUS
from app.models.booking import BookingState
from app.models.planning import PlanStatus, PlanStep, StepStatus


class ApprovalFlowError(Exception):
    """Raised when confirm/cancel cannot proceed."""


def find_plan_step(state: AgentState, step_id: str | None) -> PlanStep | None:
    """Return one plan step by id."""
    if not step_id:
        return None
    for step in state.plan.steps:
        if step.id == step_id:
            return step
    return None


def _apply_create_booking_approval(state: AgentState, payload: dict[str, object]) -> None:
    from app.guardrails.approval import parse_booking_approval

    if payload.get("action") == "create_booking" and "route" in payload:
        approval = parse_booking_approval(payload)
        state.flight_search.selected_option_id = approval.flight_id
        state.user_message = f"Book flight for {approval.passenger}"
        return

    flight_id = payload.get("flight_id")
    passenger = payload.get("passenger")
    if flight_id is not None:
        state.flight_search.selected_option_id = str(flight_id)
    if passenger is not None:
        state.user_message = f"Book flight for {passenger}"


def confirm_pending_approval(
    state: AgentState,
    *,
    settings: Settings | None = None,
) -> tuple[str, bool]:
    """Execute an approved WRITE action and clear pending approval on success."""
    if state.pending_approval is None:
        raise ApprovalFlowError("No pending approval for this conversation.")

    payload = state.pending_approval
    action = payload.get("action")
    if action != "create_booking":
        raise ApprovalFlowError(f"Unsupported approval action '{action}'.")

    step = find_plan_step(state, str(payload.get("step_id", "")))
    if step is None:
        raise ApprovalFlowError("Approval step no longer exists in the active plan.")

    resolved_settings = settings or get_settings()
    from app.agent.workers import configure_worker_registry

    configure_worker_registry(resolved_settings)
    _apply_create_booking_approval(state, payload)

    message, success = execute_approved_step(state, step)
    if success:
        state.pending_approval = None
    return message, success


def _refresh_plan_status_after_denial(state: AgentState) -> None:
    if not state.plan.steps:
        return
    if all(
        step.status in {StepStatus.COMPLETED, StepStatus.SKIPPED}
        for step in state.plan.steps
    ):
        state.plan.status = PlanStatus.COMPLETED


def finalize_approval_denial(state: AgentState, step: PlanStep | None) -> None:
    """Clear booking side effects after a denied approval — Phase 7.6."""
    state.pending_approval = None
    state.booking = BookingState()
    if step is not None:
        step.status = StepStatus.SKIPPED
        record_tool_call(
            state,
            step=step,
            status=APPROVAL_CANCELLED_STATUS,
            message="Booking request cancelled.",
        )
    _refresh_plan_status_after_denial(state)


def cancel_pending_approval(state: AgentState) -> tuple[str, bool]:
    """Abort a pending WRITE action without side effects."""
    if state.pending_approval is None:
        raise ApprovalFlowError("No pending approval for this conversation.")

    step = find_plan_step(state, str(state.pending_approval.get("step_id", "")))
    finalize_approval_denial(state, step)
    return "Booking request cancelled.", True


def run_confirm_approval(
    *,
    conversation_id: str,
    trace_id: str,
    settings: Settings | None = None,
    store: InMemoryStateStore | None = None,
) -> tuple[AgentState, str, bool]:
    """Load session state, confirm pending approval, and persist."""
    resolved_store = store or get_state_store()
    state = resolved_store.get(conversation_id)
    if state is None:
        raise ApprovalFlowError(f"Conversation '{conversation_id}' not found.")

    state.trace_id = trace_id
    message, success = confirm_pending_approval(state, settings=settings)
    resolved_store.save(state)
    return state, message, success


def run_cancel_approval(
    *,
    conversation_id: str,
    trace_id: str,
    store: InMemoryStateStore | None = None,
) -> tuple[AgentState, str, bool]:
    """Load session state, cancel pending approval, and persist."""
    resolved_store = store or get_state_store()
    state = resolved_store.get(conversation_id)
    if state is None:
        raise ApprovalFlowError(f"Conversation '{conversation_id}' not found.")

    state.trace_id = trace_id
    message, success = cancel_pending_approval(state)
    resolved_store.save(state)
    return state, message, success
