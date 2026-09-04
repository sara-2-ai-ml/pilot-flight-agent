"""Coordinator — state management, plan execution, worker delegation."""

import time

from app.agent.state import AgentState
from app.agent.tool_history import record_tool_call
from app.agent.workers import get_worker
from app.core.logging import get_logger
from app.core.observability import elapsed_ms, log_extra
from app.core.tracing import trace_span
from app.guardrails.approval import APPROVAL_STATUS, ApprovalValidationError, queue_step_for_approval
from app.guardrails.permissions import UnknownToolError, executes_directly
from app.models.planning import PlanStatus, PlanStep, StepStatus

_STUB_FAIL_PREFIX = "stub_fail_remaining:"
_logger = get_logger("agent.coordinator")


def _log_step_executed(step: PlanStep, success: bool, started_at: float) -> None:
    _logger.info(
        "step_executed",
        extra=log_extra(
            event="step_executed",
            step=step.id,
            worker=step.worker.value,
            action=step.action,
            success=success,
            latency_ms=elapsed_ms(started_at),
        ),
    )


def _completed_step_ids(state: AgentState) -> set[str]:
    return {
        step.id
        for step in state.plan.steps
        if step.status in {StepStatus.COMPLETED, StepStatus.SKIPPED}
    }


def find_next_executable_step_index(state: AgentState) -> int | None:
    """Return the index of the next pending step whose dependencies are satisfied."""
    completed = _completed_step_ids(state)

    for index, step in enumerate(state.plan.steps):
        if step.status != StepStatus.PENDING:
            continue
        if all(dep in completed for dep in step.depends_on):
            return index

    return None


def select_current_step(state: AgentState) -> PlanStep | None:
    """Select the next executable plan step and store its index on state."""
    if not state.plan.steps:
        return None

    index = find_next_executable_step_index(state)
    if index is None:
        return None

    state.plan.current_step = index
    if state.plan.status == PlanStatus.PENDING:
        state.plan.status = PlanStatus.IN_PROGRESS

    return state.plan.steps[index]


def set_stub_failures(state: AgentState, failures: dict[str, int]) -> None:
    """Test hook — fail the next N stub executions for specific step ids."""
    for step_id, count in failures.items():
        state.user_context[f"{_STUB_FAIL_PREFIX}{step_id}"] = str(count)


def _should_simulate_failure(state: AgentState, step: PlanStep) -> bool:
    key = f"{_STUB_FAIL_PREFIX}{step.id}"
    remaining = int(state.user_context.get(key, "0"))
    if remaining <= 0:
        return False

    state.user_context[key] = str(remaining - 1)
    return True


def prepare_step_retry(step: PlanStep) -> None:
    """Reset a failed step so it can be selected again."""
    step.status = StepStatus.PENDING


def _refresh_plan_status(state: AgentState) -> None:
    if not state.plan.steps:
        return

    if all(step.status == StepStatus.COMPLETED for step in state.plan.steps):
        state.plan.status = PlanStatus.COMPLETED


def mark_plan_failed(state: AgentState) -> None:
    """Mark the active plan as terminally failed."""
    if state.plan.steps:
        state.plan.status = PlanStatus.FAILED


def _run_worker_step(state: AgentState, step: PlanStep) -> tuple[str, bool]:
    """Delegate one plan step to its worker and record the outcome."""
    worker = get_worker(step.worker)
    result = worker.execute(step.action, state)

    if not result.success:
        prepare_step_retry(step)
        record_tool_call(
            state,
            step=step,
            status=StepStatus.FAILED.value,
            message=result.message,
            error_code=result.error_code,
        )
        return result.message, False

    step.status = StepStatus.COMPLETED
    record_tool_call(
        state,
        step=step,
        status=StepStatus.COMPLETED.value,
        message=result.message,
    )
    _refresh_plan_status(state)

    return result.message, True


def _queue_pending_approval(state: AgentState, step: PlanStep) -> tuple[str, bool]:
    """Queue a WRITE step for human approval without executing side effects."""
    try:
        message = queue_step_for_approval(state, step)
    except ApprovalValidationError as exc:
        prepare_step_retry(step)
        record_tool_call(
            state,
            step=step,
            status=StepStatus.FAILED.value,
            message=str(exc),
        )
        return str(exc), False

    record_tool_call(
        state,
        step=step,
        status=APPROVAL_STATUS,
        message=message,
    )
    return message, True


def execute_step(state: AgentState, step: PlanStep) -> tuple[str, bool]:
    """Execute a plan step by delegating to the matching worker."""
    with trace_span(
        f"worker:{step.id}",
        kind="worker",
        step=step.id,
        worker=step.worker.value,
        action=step.action,
    ) as span:
        step.status = StepStatus.IN_PROGRESS
        started_at = time.perf_counter()

        if _should_simulate_failure(state, step):
            message = f"Stub failed {step.worker.value}.{step.action}"
            prepare_step_retry(step)
            record_tool_call(
                state,
                step=step,
                status=StepStatus.FAILED.value,
                message=message,
            )
            span.mark_error()
            _log_step_executed(step, success=False, started_at=started_at)
            return message, False

        try:
            direct = executes_directly(worker=step.worker, action=step.action)
        except UnknownToolError as exc:
            message = str(exc)
            prepare_step_retry(step)
            record_tool_call(
                state,
                step=step,
                status=StepStatus.FAILED.value,
                message=message,
            )
            span.mark_error()
            _log_step_executed(step, success=False, started_at=started_at)
            return message, False

        if direct:
            message, success = _run_worker_step(state, step)
            if not success:
                span.mark_error()
            _log_step_executed(step, success=success, started_at=started_at)
            return message, success

        message, success = _queue_pending_approval(state, step)
        if not success:
            span.mark_error()
        _log_step_executed(step, success=success, started_at=started_at)
        return message, success


def execute_approved_step(state: AgentState, step: PlanStep) -> tuple[str, bool]:
    """Execute a WRITE step after human approval."""
    with trace_span(
        f"worker:{step.id}",
        kind="worker",
        step=step.id,
        worker=step.worker.value,
        action=step.action,
    ) as span:
        step.status = StepStatus.IN_PROGRESS
        started_at = time.perf_counter()
        message, success = _run_worker_step(state, step)
        if not success:
            span.mark_error()
        _log_step_executed(step, success=success, started_at=started_at)
        return message, success


def execute_step_stub(state: AgentState, step: PlanStep) -> tuple[str, bool]:
    """Backward-compatible alias for worker-backed step execution."""
    return execute_step(state, step)
