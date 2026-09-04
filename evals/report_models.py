"""Eval report models — Phase 12.5."""

from pydantic import BaseModel, Field


class EvalReportCaseRow(BaseModel):
    """One row in an eval report case table."""

    case_id: str
    category: str | None = None
    passed: bool
    observed_outcome: str | None = None
    outcome_score: float = Field(ge=0.0, le=1.0)
    trajectory_score: float = Field(ge=0.0, le=1.0)
    safety_score: float = Field(ge=0.0, le=1.0)
    overall_score: float = Field(ge=0.0, le=1.0)
    failures: list[str] = Field(default_factory=list)


class EvalReportSummary(BaseModel):
    """Top-level counters for an eval run."""

    total: int = Field(ge=0)
    passed: int = Field(ge=0)
    failed: int = Field(ge=0)
    pass_rate: float = Field(ge=0.0, le=1.0)


class EvalReportMetrics(BaseModel):
    """Aggregate metric scores for an eval run."""

    outcome_score: float = Field(ge=0.0, le=1.0)
    trajectory_score: float = Field(ge=0.0, le=1.0)
    safety_score: float = Field(ge=0.0, le=1.0)
    overall_score: float = Field(ge=0.0, le=1.0)


class EvalReport(BaseModel):
    """Structured eval report for JSON and markdown export."""

    title: str
    run_type: str
    generated_at: str
    summary: EvalReportSummary
    metrics: EvalReportMetrics | None = None
    cases: list[EvalReportCaseRow] = Field(default_factory=list)
