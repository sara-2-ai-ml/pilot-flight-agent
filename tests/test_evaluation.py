"""Evaluation model tests — Phase 3.1."""

import pytest
from pydantic import ValidationError

from app.models.agent import EvaluationResult, EvaluationStatus


def test_evaluation_status_values() -> None:
    assert EvaluationStatus.CONTINUE.value == "continue"
    assert EvaluationStatus.RETRY.value == "retry"
    assert EvaluationStatus.REPLAN.value == "replan"
    assert EvaluationStatus.ASK_USER.value == "ask_user"
    assert EvaluationStatus.FAIL.value == "fail"


def test_evaluation_result_accepts_valid_status() -> None:
    result = EvaluationResult(
        status=EvaluationStatus.ASK_USER,
        issue="Public flight API does not provide fare prices.",
        message="I can show scheduled flights, but not reliable cheapest fares.",
    )

    assert result.status == EvaluationStatus.ASK_USER
    assert result.issue is not None
    assert result.message is not None


def test_evaluation_result_serializes_to_json() -> None:
    result = EvaluationResult(status=EvaluationStatus.CONTINUE)
    restored = EvaluationResult.model_validate_json(result.model_dump_json())

    assert restored.status == EvaluationStatus.CONTINUE
    assert restored.issue is None


def test_evaluation_result_rejects_invalid_status() -> None:
    with pytest.raises(ValidationError):
        EvaluationResult.model_validate({"status": "keep_going"})
