"""Tool call history — audit trail for worker executions."""

from app.agent.state import AgentState
from app.models.agent import ToolCallRecord
from app.models.planning import PlanStep


def record_tool_call(
    state: AgentState,
    *,
    step: PlanStep,
    status: str,
    message: str | None = None,
    error_code: str | None = None,
) -> ToolCallRecord:
    """Append one worker execution to session tool history."""
    record = ToolCallRecord(
        tool=step.worker.value,
        action=step.action,
        status=status,
        step_id=step.id,
        trace_id=state.trace_id,
        message=message,
        error_code=error_code,
        iteration=state.iteration_count,
    )
    state.tool_history.append(record)
    return record
