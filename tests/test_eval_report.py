"""Eval report tests — Phase 12.5."""

import json

import pytest

from evals.regression import run_regression_evals
from evals.report import (
    build_eval_report,
    format_eval_report_json,
    format_eval_report_markdown,
    write_eval_report,
)
from evals.runners import run_all_evals


def test_build_eval_report_from_full_suite(tmp_path) -> None:
    summary = run_all_evals(booking_db_path=tmp_path / "bookings.db")
    report = build_eval_report(summary, run_type="full")

    assert report.run_type == "full"
    assert report.summary.total == summary.total
    assert report.summary.passed == summary.passed
    assert report.summary.pass_rate == pytest.approx(1.0)
    assert report.metrics is not None
    assert report.metrics.overall_score == pytest.approx(1.0)
    assert len(report.cases) == summary.total


def test_format_eval_report_json_is_valid(tmp_path) -> None:
    summary = run_regression_evals(
        booking_db_path=tmp_path / "bookings.db",
        enforce_thresholds=False,
    )
    report = build_eval_report(summary, run_type="regression")
    payload = json.loads(format_eval_report_json(report))

    assert payload["run_type"] == "regression"
    assert payload["summary"]["total"] == len(payload["cases"])
    assert payload["cases"][0]["case_id"]


def test_format_eval_report_markdown_includes_tables(tmp_path) -> None:
    summary = run_regression_evals(
        booking_db_path=tmp_path / "bookings.db",
        enforce_thresholds=False,
    )
    report = build_eval_report(summary, run_type="regression")
    markdown = format_eval_report_markdown(report)

    assert "# Pilot Flight Agent — Eval Report" in markdown
    assert "## Aggregate scores" in markdown
    assert "## Cases" in markdown
    assert "| Case | Category | Pass |" in markdown
    assert report.cases[0].case_id in markdown


def test_format_eval_report_markdown_lists_failures() -> None:
    from evals.report_models import EvalReport, EvalReportCaseRow, EvalReportSummary

    report = EvalReport(
        title="Test Report",
        run_type="full",
        generated_at="2026-09-03T09:00:00+00:00",
        summary=EvalReportSummary(total=1, passed=0, failed=1, pass_rate=0.0),
        cases=[
            EvalReportCaseRow(
                case_id="broken-case",
                category="happy_path",
                passed=False,
                outcome_score=0.0,
                trajectory_score=0.0,
                safety_score=0.0,
                overall_score=0.0,
                failures=["expected message to contain 'flights'"],
            ),
        ],
    )

    markdown = format_eval_report_markdown(report)

    assert "## Failures" in markdown
    assert "### broken-case" in markdown
    assert "expected message to contain 'flights'" in markdown


def test_write_eval_report_creates_json_and_markdown(tmp_path) -> None:
    summary = run_regression_evals(
        booking_db_path=tmp_path / "bookings.db",
        enforce_thresholds=False,
    )
    output_dir = tmp_path / "reports"
    json_path, markdown_path = write_eval_report(
        summary,
        output_dir,
        stem="regression-report",
        run_type="regression",
    )

    assert json_path.exists()
    assert markdown_path.exists()
    assert json_path.name == "regression-report.json"
    assert markdown_path.name == "regression-report.md"

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["run_type"] == "regression"
    assert "Aggregate scores" in markdown_path.read_text(encoding="utf-8")
