"""Regression eval tests — Phase 12.4."""

import pytest

from evals.datasets.regression import (
    load_regression_manifest,
    regression_manifest_path,
    resolve_regression_cases,
)
from evals.regression import (
    RegressionGateError,
    assert_regression_passed,
    check_regression_thresholds,
    run_regression_evals,
)
from evals.runners import run_eval_case


def test_regression_manifest_exists_and_loads() -> None:
    manifest = load_regression_manifest()

    assert regression_manifest_path().exists()
    assert len(manifest.cases) >= 8
    assert manifest.minimum_scores.pass_rate == 1.0


def test_regression_cases_resolve_to_dataset_entries() -> None:
    manifest = load_regression_manifest()
    entries = resolve_regression_cases(manifest)

    assert len(entries) == len(manifest.cases)
    assert entries[0].case.id == manifest.cases[0].id
    assert all(entry.case.id for entry in entries)


def test_regression_evals_all_pass(tmp_path) -> None:
    summary = run_regression_evals(
        booking_db_path=tmp_path / "bookings.db",
        enforce_thresholds=False,
    )
    manifest = load_regression_manifest()

    assert summary.total == len(manifest.cases)
    assert summary.passed == summary.total
    assert summary.failed == 0
    assert summary.metrics is not None
    assert summary.metrics.overall_score == pytest.approx(1.0)


def test_regression_gate_enforces_thresholds(tmp_path) -> None:
    summary = run_regression_evals(booking_db_path=tmp_path / "bookings.db")

    assert summary.passed == summary.total
    assert_regression_passed(summary)


def test_regression_gate_raises_on_failed_case(tmp_path) -> None:
    manifest = load_regression_manifest()
    entry = resolve_regression_cases(manifest)[0]

    broken = entry.case.model_copy(deep=True)
    broken.expectations.message_contains = ["__regression_should_never_match__"]
    failed = run_eval_case(
        broken,
        category=entry.category,
        booking_db_path=tmp_path / "bookings.db",
    )

    summary = run_regression_evals(
        booking_db_path=tmp_path / "bookings.db",
        enforce_thresholds=False,
    )
    summary = summary.model_copy(
        update={
            "passed": summary.passed - 1,
            "failed": summary.failed + 1,
            "results": [failed, *summary.results[1:]],
        },
    )

    failures = check_regression_thresholds(summary, manifest)

    assert failures
    assert any("pass_rate" in item for item in failures)
    assert any("happy-search-tia-fra" in item for item in failures)

    with pytest.raises(RegressionGateError):
        assert_regression_passed(summary, manifest)


def test_run_regression_evals_raises_when_gate_fails(tmp_path) -> None:
    manifest = load_regression_manifest().model_copy(deep=True)
    manifest.minimum_scores.pass_rate = 1.0
    manifest.minimum_scores.overall_score = 1.01

    with pytest.raises(RegressionGateError, match="overall_score"):
        run_regression_evals(
            booking_db_path=tmp_path / "bookings.db",
            manifest=manifest,
        )
