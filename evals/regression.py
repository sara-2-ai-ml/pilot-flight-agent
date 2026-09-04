"""Regression eval gate — run curated cases and enforce score thresholds."""

from __future__ import annotations

from pathlib import Path

from evals.datasets.regression import (
    RegressionCaseEntry,
    RegressionManifest,
    load_regression_manifest,
    resolve_regression_cases,
)
from evals.metrics.models import EvalRunMetrics
from evals.runners.http_runner import run_eval_case
from evals.runners.results import EvalRunSummary


class RegressionGateError(Exception):
    """Raised when regression evals fail to meet required thresholds."""

    def __init__(self, failures: list[str]) -> None:
        self.failures = failures
        super().__init__("\n".join(failures))


def check_regression_thresholds(
    summary: EvalRunSummary,
    manifest: RegressionManifest,
) -> list[str]:
    """Return threshold violations for a regression run."""
    thresholds = manifest.minimum_scores
    failures: list[str] = []

    if summary.pass_rate < thresholds.pass_rate:
        failures.append(
            f"pass_rate {summary.pass_rate:.3f} below minimum {thresholds.pass_rate:.3f}",
        )

    if summary.metrics is None:
        failures.append("regression run missing aggregate metrics")
        return failures

    metrics = summary.metrics
    checks = (
        ("outcome_score", metrics.outcome_score, thresholds.outcome_score),
        ("trajectory_score", metrics.trajectory_score, thresholds.trajectory_score),
        ("safety_score", metrics.safety_score, thresholds.safety_score),
        ("overall_score", metrics.overall_score, thresholds.overall_score),
    )
    for name, actual, minimum in checks:
        if actual < minimum:
            failures.append(f"{name} {actual:.3f} below minimum {minimum:.3f}")

    for result in summary.results:
        if not result.passed:
            failures.append(f"case '{result.case_id}' failed: {', '.join(result.failures)}")

    return failures


def run_regression_evals(
    *,
    booking_db_path: str | Path | None = None,
    manifest: RegressionManifest | None = None,
    enforce_thresholds: bool = True,
) -> EvalRunSummary:
    """Run the curated regression set and optionally enforce score thresholds."""
    resolved_manifest = manifest or load_regression_manifest()
    entries = resolve_regression_cases(resolved_manifest)

    results = [
        run_eval_case(
            entry.case,
            category=entry.category,
            booking_db_path=booking_db_path,
        )
        for entry in entries
    ]
    passed = sum(1 for result in results if result.passed)
    summary = EvalRunSummary(
        total=len(results),
        passed=passed,
        failed=len(results) - passed,
        results=results,
    )

    from evals.metrics.scoring import score_results

    cases = [entry.case for entry in entries]
    summary = summary.model_copy(
        update={"metrics": score_results(cases, summary)},
    )

    if enforce_thresholds:
        failures = check_regression_thresholds(summary, resolved_manifest)
        if failures:
            raise RegressionGateError(failures)

    return summary


def assert_regression_passed(
    summary: EvalRunSummary,
    manifest: RegressionManifest | None = None,
) -> None:
    """Raise RegressionGateError when the regression gate fails."""
    failures = check_regression_thresholds(
        summary,
        manifest or load_regression_manifest(),
    )
    if failures:
        raise RegressionGateError(failures)
