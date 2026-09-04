"""Eval run result models — Phase 12.2, Phase 12.3."""

from pydantic import BaseModel, Field

from evals.datasets.models import EvalAction, EvalCategory, ExpectedOutcome
from evals.metrics.models import EvalCaseMetrics, EvalRunMetrics


class EvalTurnResult(BaseModel):
    """Captured HTTP outcome for one executed turn."""

    action: EvalAction
    http_status: int
    message: str
    success: bool | None = None


class EvalCaseResult(BaseModel):
    """Pass/fail outcome for one eval case."""

    case_id: str
    category: EvalCategory | None = None
    passed: bool
    failures: list[str] = Field(default_factory=list)
    turns: list[EvalTurnResult] = Field(default_factory=list)
    conversation_id: str | None = None
    observed_outcome: ExpectedOutcome | None = None
    metrics: EvalCaseMetrics | None = None


class EvalRunSummary(BaseModel):
    """Aggregate results for a batch of eval cases."""

    total: int
    passed: int
    failed: int
    results: list[EvalCaseResult] = Field(default_factory=list)
    metrics: EvalRunMetrics | None = None

    @property
    def pass_rate(self) -> float:
        if self.total == 0:
            return 1.0
        return self.passed / self.total
