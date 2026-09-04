"""Evaluation metrics tests — Phase 12.3."""

import pytest

from evals.datasets import EvalCategory, ExpectedOutcome, load_dataset
from evals.metrics import score_case, score_outcome
from evals.runners import run_all_evals, run_eval_case
from evals.runners.results import EvalCaseResult, EvalTurnResult


def test_score_outcome_perfect_match() -> None:
    case = next(
        case for case in load_dataset(EvalCategory.HAPPY_PATH).cases
        if case.id == "happy-search-tia-fra"
    )
    result = EvalCaseResult(
        case_id=case.id,
        passed=True,
        observed_outcome=ExpectedOutcome.ASK_USER,
    )

    metrics = score_outcome(case, result)

    assert metrics.score == 1.0
    assert metrics.expected == ExpectedOutcome.ASK_USER
    assert metrics.observed == ExpectedOutcome.ASK_USER


def test_score_outcome_mismatch_scores_zero() -> None:
    case = next(
        case for case in load_dataset(EvalCategory.INJECTION).cases
        if case.id == "injection-ignore-instructions"
    )
    result = EvalCaseResult(
        case_id=case.id,
        passed=False,
        observed_outcome=ExpectedOutcome.PENDING_APPROVAL,
    )

    metrics = score_outcome(case, result)

    assert metrics.score == 0.0


def test_run_eval_case_includes_case_metrics(tmp_path) -> None:
    case = next(
        case for case in load_dataset(EvalCategory.HAPPY_PATH).cases
        if case.id == "happy-search-tia-fra"
    )

    result = run_eval_case(
        case,
        category=EvalCategory.HAPPY_PATH,
        booking_db_path=tmp_path / "bookings.db",
    )

    assert result.metrics is not None
    assert result.metrics.outcome.score == 1.0
    assert result.metrics.trajectory.turn_count == 1
    assert result.metrics.trajectory.tool_call_count >= 1
    assert result.metrics.safety.unauthorized_write is False
    assert result.metrics.overall_score == pytest.approx(1.0)


def test_injection_case_scores_safety_on_block(tmp_path) -> None:
    case = next(
        case for case in load_dataset(EvalCategory.INJECTION).cases
        if case.id == "injection-ignore-instructions"
    )

    result = run_eval_case(
        case,
        category=EvalCategory.INJECTION,
        booking_db_path=tmp_path / "bookings.db",
    )

    assert result.metrics is not None
    assert result.metrics.safety.score == 1.0
    assert result.metrics.safety.guard_blocked is True
    assert result.metrics.trajectory.score == 1.0
    assert result.metrics.trajectory.tool_call_count == 0


def test_hitl_confirm_metrics_show_respected_write_path(tmp_path) -> None:
    case = next(
        case for case in load_dataset(EvalCategory.HITL).cases
        if case.id == "hitl-confirm-booking"
    )

    result = run_eval_case(
        case,
        category=EvalCategory.HITL,
        booking_db_path=tmp_path / "bookings.db",
    )

    assert result.metrics is not None
    assert result.metrics.trajectory.hitl_respected is True
    assert result.metrics.safety.unauthorized_write is False
    assert result.metrics.outcome.score == 1.0


def test_run_all_evals_includes_aggregate_metrics(tmp_path) -> None:
    summary = run_all_evals(booking_db_path=tmp_path / "bookings.db")

    assert summary.metrics is not None
    assert summary.metrics.outcome_score == pytest.approx(1.0)
    assert summary.metrics.trajectory_score == pytest.approx(1.0)
    assert summary.metrics.safety_score == pytest.approx(1.0)
    assert summary.metrics.overall_score == pytest.approx(1.0)
    assert len(summary.metrics.cases) == summary.total


def test_score_case_without_state_still_returns_metrics() -> None:
    case = next(
        case for case in load_dataset(EvalCategory.INJECTION).cases
        if case.id == "injection-ignore-instructions"
    )
    result = EvalCaseResult(
        case_id=case.id,
        passed=True,
        observed_outcome=ExpectedOutcome.BLOCKED,
        turns=[
            EvalTurnResult(
                action=case.turns[0].action,
                http_status=400,
                message="Message contains disallowed prompt manipulation and was blocked.",
            ),
        ],
    )

    metrics = score_case(case, result, state=None)

    assert metrics.safety.guard_blocked is True
    assert metrics.trajectory.score == 1.0
