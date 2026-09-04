"""Evaluation dataset structure tests — Phase 12.1."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from evals.datasets import (
    EvalAction,
    EvalCategory,
    EvalDataset,
    EvalTurn,
    ExpectedOutcome,
    dataset_path,
    datasets_dir,
    list_dataset_files,
    load_all_cases,
    load_all_datasets,
    load_dataset,
)


def test_datasets_directory_contains_registered_files() -> None:
    root = datasets_dir()
    files = list_dataset_files()

    assert root.is_dir()
    assert len(files) == len(EvalCategory)
    for path in files:
        assert path.exists()
        assert path.parent == root


def test_each_category_loads_and_matches_filename() -> None:
    for category in EvalCategory:
        dataset = load_dataset(category)

        assert dataset.category == category
        assert len(dataset.cases) >= 1
        assert dataset.description


def test_load_all_datasets_returns_every_category() -> None:
    datasets = load_all_datasets()

    assert set(datasets) == set(EvalCategory)
    assert sum(len(dataset.cases) for dataset in datasets.values()) == len(load_all_cases())


def test_case_ids_are_globally_unique() -> None:
    ids = [case.id for case in load_all_cases()]

    assert len(ids) == len(set(ids))


@pytest.mark.parametrize(
    ("category", "expected_case_id"),
    [
        (EvalCategory.HAPPY_PATH, "happy-search-tia-fra"),
        (EvalCategory.AMBIGUOUS, "ambiguous-cheapest-fare"),
        (EvalCategory.INJECTION, "injection-ignore-instructions"),
        (EvalCategory.HITL, "hitl-confirm-booking"),
        (EvalCategory.SAFETY, "safety-empty-message"),
    ],
)
def test_representative_cases_exist(category: EvalCategory, expected_case_id: str) -> None:
    dataset = load_dataset(category)
    case_ids = {case.id for case in dataset.cases}

    assert expected_case_id in case_ids


def test_happy_path_case_expects_search_list_without_booking_write() -> None:
    dataset = load_dataset(EvalCategory.HAPPY_PATH)
    case = next(case for case in dataset.cases if case.id == "happy-search-tia-fra")

    assert case.turns[0].action == EvalAction.CHAT
    assert case.expectations.outcome == ExpectedOutcome.ASK_USER
    assert case.expectations.pending_approval is False
    assert case.expectations.booking_created is False


def test_injection_cases_expect_blocked_responses() -> None:
    dataset = load_dataset(EvalCategory.INJECTION)

    for case in dataset.cases:
        assert case.expectations.outcome == ExpectedOutcome.BLOCKED
        assert case.expectations.http_status == 400
        assert "prompt manipulation" in case.expectations.message_contains


def test_hitl_confirm_case_includes_confirm_turn() -> None:
    dataset = load_dataset(EvalCategory.HITL)
    case = next(case for case in dataset.cases if case.id == "hitl-confirm-booking")

    assert [turn.action for turn in case.turns] == [EvalAction.CHAT, EvalAction.CONFIRM]
    assert case.expectations.booking_created is True
    assert case.expectations.plan_status == "completed"


def test_chat_turn_requires_message() -> None:
    with pytest.raises(ValidationError):
        EvalTurn(action=EvalAction.CHAT, message=None)


def test_dataset_rejects_duplicate_case_ids_in_one_file(tmp_path: Path) -> None:
    payload = {
        "category": "happy_path",
        "description": "duplicate ids",
        "cases": [
            {
                "id": "dup",
                "description": "first",
                "turns": [{"action": "chat", "message": "hello"}],
                "expectations": {"outcome": "blocked", "http_status": 400},
            },
            {
                "id": "dup",
                "description": "second",
                "turns": [{"action": "chat", "message": "hello"}],
                "expectations": {"outcome": "blocked", "http_status": 400},
            },
        ],
    }

    with pytest.raises(ValidationError):
        EvalDataset.model_validate(payload)


def test_dataset_path_helper_matches_category() -> None:
    assert dataset_path(EvalCategory.INJECTION).name == "injection.json"
