"""Load and validate evaluation datasets from JSON files."""

from __future__ import annotations

import json
from pathlib import Path

from evals.datasets.models import EvalCase, EvalCategory, EvalDataset

_DATASETS_DIR = Path(__file__).resolve().parent

_CATEGORY_FILES: dict[EvalCategory, str] = {
    EvalCategory.HAPPY_PATH: "happy_path.json",
    EvalCategory.AMBIGUOUS: "ambiguous.json",
    EvalCategory.INJECTION: "injection.json",
    EvalCategory.HITL: "hitl.json",
    EvalCategory.SAFETY: "safety.json",
}


def datasets_dir() -> Path:
    """Return the root directory containing dataset JSON files."""
    return _DATASETS_DIR


def dataset_path(category: EvalCategory) -> Path:
    """Resolve the JSON file path for a dataset category."""
    return _DATASETS_DIR / _CATEGORY_FILES[category]


def load_dataset(category: EvalCategory) -> EvalDataset:
    """Load and validate one dataset category from disk."""
    path = dataset_path(category)
    payload = json.loads(path.read_text(encoding="utf-8"))
    dataset = EvalDataset.model_validate(payload)
    if dataset.category != category:
        raise ValueError(
            f"Dataset file {path.name} declares category '{dataset.category.value}', "
            f"expected '{category.value}'",
        )
    return dataset


def load_all_datasets() -> dict[EvalCategory, EvalDataset]:
    """Load every registered dataset category."""
    return {category: load_dataset(category) for category in EvalCategory}


def load_all_cases() -> list[EvalCase]:
    """Flatten all cases across datasets in stable category order."""
    cases: list[EvalCase] = []
    for category in EvalCategory:
        cases.extend(load_dataset(category).cases)
    return cases


def list_dataset_files() -> list[Path]:
    """Return paths for all registered dataset JSON files."""
    return [dataset_path(category) for category in EvalCategory]
