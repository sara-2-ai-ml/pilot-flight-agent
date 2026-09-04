"""Evaluation runner tests — Phase 12.2."""

import pytest

from evals.datasets import EvalCategory, ExpectedOutcome, load_all_cases, load_dataset
from evals.runners import (
    EvalHttpRunner,
    run_all_evals,
    run_category_evals,
    run_eval_case,
)


def test_run_eval_case_happy_path(tmp_path) -> None:
    case = next(
        case for case in load_dataset(EvalCategory.HAPPY_PATH).cases
        if case.id == "happy-search-tia-fra"
    )

    result = run_eval_case(
        case,
        category=EvalCategory.HAPPY_PATH,
        booking_db_path=tmp_path / "bookings.db",
    )

    assert result.passed is True
    assert result.failures == []
    assert result.observed_outcome == ExpectedOutcome.ASK_USER
    assert len(result.turns) == 1
    assert result.turns[0].http_status == 200


def test_run_eval_case_injection_blocked(tmp_path) -> None:
    case = next(
        case for case in load_dataset(EvalCategory.INJECTION).cases
        if case.id == "injection-ignore-instructions"
    )

    result = run_eval_case(
        case,
        category=EvalCategory.INJECTION,
        booking_db_path=tmp_path / "bookings.db",
    )

    assert result.passed is True
    assert result.observed_outcome == ExpectedOutcome.BLOCKED
    assert result.turns[0].http_status == 400


def test_run_eval_case_hitl_confirm_creates_booking(tmp_path) -> None:
    case = next(
        case for case in load_dataset(EvalCategory.HITL).cases
        if case.id == "hitl-confirm-booking"
    )

    result = run_eval_case(
        case,
        category=EvalCategory.HITL,
        booking_db_path=tmp_path / "bookings.db",
    )

    assert result.passed is True
    assert result.observed_outcome == ExpectedOutcome.COMPLETED
    assert [turn.action.value for turn in result.turns] == ["chat", "confirm"]


def test_run_category_evals_executes_all_cases_in_category(tmp_path) -> None:
    dataset = load_dataset(EvalCategory.SAFETY)
    summary = run_category_evals(
        EvalCategory.SAFETY,
        booking_db_path=tmp_path / "bookings.db",
    )

    assert summary.total == len(dataset.cases)
    assert summary.passed == summary.total
    assert summary.failed == 0


def test_run_all_evals_executes_full_suite(tmp_path) -> None:
    summary = run_all_evals(booking_db_path=tmp_path / "bookings.db")

    assert summary.total == len(load_all_cases())
    assert summary.passed == summary.total
    assert summary.failed == 0
    assert summary.pass_rate == 1.0


def test_runner_reports_expectation_failures(tmp_path) -> None:
    case = next(
        case for case in load_dataset(EvalCategory.HAPPY_PATH).cases
        if case.id == "happy-search-tia-fra"
    ).model_copy(deep=True)
    case.expectations.message_contains = ["this fragment will never appear"]

    result = run_eval_case(case, booking_db_path=tmp_path / "bookings.db")

    assert result.passed is False
    assert any("expected message to contain" in failure for failure in result.failures)


def test_eval_http_runner_reuses_client_for_multi_turn_case(tmp_path) -> None:
    case = next(
        case for case in load_dataset(EvalCategory.HITL).cases
        if case.id == "hitl-cancel-booking"
    )
    runner = EvalHttpRunner(booking_db_path=tmp_path / "bookings.db")

    result = runner.run_case(case, category=EvalCategory.HITL)

    assert result.passed is True
    assert result.observed_outcome == ExpectedOutcome.CANCELLED
    assert len(result.turns) == 2
