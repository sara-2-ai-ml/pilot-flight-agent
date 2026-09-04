"""Regression manifest models and loader — Phase 12.4."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field, model_validator

from evals.datasets.loader import datasets_dir, load_dataset
from evals.datasets.models import EvalCase, EvalCategory

_REGRESSION_FILE = "regression.json"


class RegressionThresholds(BaseModel):
    """Minimum acceptable scores for the regression gate."""

    pass_rate: float = Field(default=1.0, ge=0.0, le=1.0)
    outcome_score: float = Field(default=1.0, ge=0.0, le=1.0)
    trajectory_score: float = Field(default=1.0, ge=0.0, le=1.0)
    safety_score: float = Field(default=1.0, ge=0.0, le=1.0)
    overall_score: float = Field(default=1.0, ge=0.0, le=1.0)


class RegressionCaseRef(BaseModel):
    """Pointer to a case defined in a category dataset."""

    id: str = Field(min_length=1)
    category: EvalCategory


class RegressionManifest(BaseModel):
    """Curated regression set and score thresholds."""

    description: str = Field(min_length=1)
    minimum_scores: RegressionThresholds = Field(default_factory=RegressionThresholds)
    cases: list[RegressionCaseRef] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_case_refs(self) -> RegressionManifest:
        refs = [(item.category, item.id) for item in self.cases]
        if len(refs) != len(set(refs)):
            raise ValueError("regression case references must be unique")
        return self


class RegressionCaseEntry(BaseModel):
    """Resolved regression case with its source category."""

    category: EvalCategory
    case: EvalCase


def regression_manifest_path() -> Path:
    return datasets_dir() / _REGRESSION_FILE


def load_regression_manifest() -> RegressionManifest:
    """Load and validate the regression manifest from disk."""
    path = regression_manifest_path()
    payload = json.loads(path.read_text(encoding="utf-8"))
    return RegressionManifest.model_validate(payload)


def resolve_regression_cases(
    manifest: RegressionManifest | None = None,
) -> list[RegressionCaseEntry]:
    """Resolve manifest references to concrete eval cases."""
    resolved_manifest = manifest or load_regression_manifest()
    entries: list[RegressionCaseEntry] = []

    for ref in resolved_manifest.cases:
        dataset = load_dataset(ref.category)
        match = next((case for case in dataset.cases if case.id == ref.id), None)
        if match is None:
            raise ValueError(
                f"Regression case '{ref.id}' not found in {ref.category.value} dataset",
            )
        entries.append(RegressionCaseEntry(category=ref.category, case=match))

    return entries
