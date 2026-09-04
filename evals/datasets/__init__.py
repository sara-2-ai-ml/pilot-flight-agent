"""Evaluation datasets — structured agent trajectory scenarios."""

from evals.datasets.loader import (
    dataset_path,
    datasets_dir,
    list_dataset_files,
    load_all_cases,
    load_all_datasets,
    load_dataset,
)
from evals.datasets.models import (
    EvalAction,
    EvalCase,
    EvalCategory,
    EvalDataset,
    EvalExpectations,
    EvalTurn,
    ExpectedOutcome,
)
from evals.datasets.regression import (
    RegressionCaseEntry,
    RegressionCaseRef,
    RegressionManifest,
    RegressionThresholds,
    load_regression_manifest,
    regression_manifest_path,
    resolve_regression_cases,
)

__all__ = [
    "EvalAction",
    "EvalCase",
    "EvalCategory",
    "EvalDataset",
    "EvalExpectations",
    "EvalTurn",
    "ExpectedOutcome",
    "RegressionCaseEntry",
    "RegressionCaseRef",
    "RegressionManifest",
    "RegressionThresholds",
    "dataset_path",
    "datasets_dir",
    "list_dataset_files",
    "load_all_cases",
    "load_all_datasets",
    "load_dataset",
    "load_regression_manifest",
    "regression_manifest_path",
    "resolve_regression_cases",
]
