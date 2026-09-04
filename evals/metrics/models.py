"""Evaluation metric models — Phase 12.3."""

from pydantic import BaseModel, Field

from evals.datasets.models import ExpectedOutcome


class OutcomeMetrics(BaseModel):
    """Did the run match the expected terminal outcome?"""

    score: float = Field(ge=0.0, le=1.0)
    expected: ExpectedOutcome
    observed: ExpectedOutcome | None = None
    passed: bool


class TrajectoryMetrics(BaseModel):
    """How the agent executed the plan and tool trajectory."""

    score: float = Field(ge=0.0, le=1.0)
    turn_count: int = Field(ge=0)
    tool_call_count: int = Field(ge=0)
    failed_tool_calls: int = Field(ge=0)
    plan_steps_completed: int = Field(ge=0)
    plan_steps_total: int = Field(ge=0)
    hitl_respected: bool | None = None


class SafetyMetrics(BaseModel):
    """Guardrail and write-safety behavior."""

    score: float = Field(ge=0.0, le=1.0)
    guard_blocked: bool | None = None
    unauthorized_write: bool = False
    unsafe_output: bool = False


class EvalCaseMetrics(BaseModel):
    """Per-case scores across outcome, trajectory, and safety."""

    case_id: str
    outcome: OutcomeMetrics
    trajectory: TrajectoryMetrics
    safety: SafetyMetrics
    overall_score: float = Field(ge=0.0, le=1.0)


class EvalRunMetrics(BaseModel):
    """Aggregate scores for an eval batch."""

    outcome_score: float = Field(ge=0.0, le=1.0)
    trajectory_score: float = Field(ge=0.0, le=1.0)
    safety_score: float = Field(ge=0.0, le=1.0)
    overall_score: float = Field(ge=0.0, le=1.0)
    cases: list[EvalCaseMetrics] = Field(default_factory=list)
