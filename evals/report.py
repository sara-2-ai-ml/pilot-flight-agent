"""Eval report generation — JSON and markdown export."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from evals.report_models import (
    EvalReport,
    EvalReportCaseRow,
    EvalReportMetrics,
    EvalReportSummary,
)
from evals.runners.results import EvalRunSummary


def build_eval_report(
    summary: EvalRunSummary,
    *,
    title: str = "Pilot Flight Agent — Eval Report",
    run_type: str = "full",
    generated_at: datetime | None = None,
) -> EvalReport:
    """Build a structured report from an eval run summary."""
    timestamp = generated_at or datetime.now(tz=UTC)
    metrics = None
    if summary.metrics is not None:
        metrics = EvalReportMetrics(
            outcome_score=summary.metrics.outcome_score,
            trajectory_score=summary.metrics.trajectory_score,
            safety_score=summary.metrics.safety_score,
            overall_score=summary.metrics.overall_score,
        )

    cases: list[EvalReportCaseRow] = []
    for result in summary.results:
        case_metrics = result.metrics
        cases.append(
            EvalReportCaseRow(
                case_id=result.case_id,
                category=result.category.value if result.category else None,
                passed=result.passed,
                observed_outcome=(
                    result.observed_outcome.value if result.observed_outcome else None
                ),
                outcome_score=case_metrics.outcome.score if case_metrics else 0.0,
                trajectory_score=case_metrics.trajectory.score if case_metrics else 0.0,
                safety_score=case_metrics.safety.score if case_metrics else 0.0,
                overall_score=case_metrics.overall_score if case_metrics else 0.0,
                failures=list(result.failures),
            ),
        )

    return EvalReport(
        title=title,
        run_type=run_type,
        generated_at=timestamp.isoformat(),
        summary=EvalReportSummary(
            total=summary.total,
            passed=summary.passed,
            failed=summary.failed,
            pass_rate=summary.pass_rate,
        ),
        metrics=metrics,
        cases=cases,
    )


def format_eval_report_json(report: EvalReport, *, indent: int = 2) -> str:
    """Serialize a report to pretty-printed JSON."""
    return json.dumps(report.model_dump(), indent=indent)


def format_eval_report_markdown(report: EvalReport) -> str:
    """Render a human-readable markdown report."""
    lines = [
        f"# {report.title}",
        "",
        f"- **Run type:** {report.run_type}",
        f"- **Generated:** {report.generated_at}",
        f"- **Pass rate:** {report.summary.passed}/{report.summary.total} "
        f"({report.summary.pass_rate * 100:.0f}%)",
        "",
    ]

    if report.metrics is not None:
        lines.extend(
            [
                "## Aggregate scores",
                "",
                "| Metric | Score |",
                "|--------|------:|",
                f"| Outcome | {report.metrics.outcome_score:.2f} |",
                f"| Trajectory | {report.metrics.trajectory_score:.2f} |",
                f"| Safety | {report.metrics.safety_score:.2f} |",
                f"| Overall | {report.metrics.overall_score:.2f} |",
                "",
            ],
        )

    lines.extend(
        [
            "## Cases",
            "",
            "| Case | Category | Pass | Outcome | Trajectory | Safety | Overall |",
            "|------|----------|:----:|--------:|-----------:|-------:|--------:|",
        ],
    )

    for case in report.cases:
        pass_mark = "yes" if case.passed else "no"
        category = case.category or "-"
        lines.append(
            f"| {case.case_id} | {category} | {pass_mark} | "
            f"{case.outcome_score:.2f} | {case.trajectory_score:.2f} | "
            f"{case.safety_score:.2f} | {case.overall_score:.2f} |",
        )

    failed_cases = [case for case in report.cases if not case.passed]
    if failed_cases:
        lines.extend(["", "## Failures", ""])
        for case in failed_cases:
            lines.append(f"### {case.case_id}")
            for failure in case.failures:
                lines.append(f"- {failure}")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def write_eval_report(
    summary: EvalRunSummary,
    output_dir: str | Path,
    *,
    stem: str = "eval-report",
    title: str = "Pilot Flight Agent — Eval Report",
    run_type: str = "full",
) -> tuple[Path, Path]:
    """Write JSON and markdown reports for an eval run."""
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    report = build_eval_report(summary, title=title, run_type=run_type)

    json_path = destination / f"{stem}.json"
    markdown_path = destination / f"{stem}.md"
    json_path.write_text(format_eval_report_json(report), encoding="utf-8")
    markdown_path.write_text(format_eval_report_markdown(report), encoding="utf-8")
    return json_path, markdown_path
