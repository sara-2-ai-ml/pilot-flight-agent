"""Planning domain models — Plan, PlanStep, dependencies."""

from enum import Enum
from typing import Self

from pydantic import BaseModel, Field, field_validator, model_validator


class PlanStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class StepStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class Worker(str, Enum):
    FLIGHT = "flight"
    BOOKING = "booking"


class PlanStep(BaseModel):
    id: str = Field(min_length=1)
    worker: Worker
    action: str = Field(min_length=1)
    depends_on: list[str] = Field(default_factory=list)
    status: StepStatus = StepStatus.PENDING

    @field_validator("depends_on")
    @classmethod
    def depends_on_entries_are_non_empty(cls, value: list[str]) -> list[str]:
        if any(not dep for dep in value):
            raise ValueError("dependency ids must be non-empty")
        return value


class Plan(BaseModel):
    goal: str = ""
    steps: list[PlanStep] = Field(default_factory=list)
    current_step: int = Field(default=0, ge=0)
    status: PlanStatus = PlanStatus.PENDING

    @model_validator(mode="after")
    def validate_step_graph(self) -> Self:
        step_ids = [step.id for step in self.steps]
        if len(set(step_ids)) != len(step_ids):
            raise ValueError("plan steps must have unique ids")

        known_ids = set(step_ids)
        for step in self.steps:
            unknown = set(step.depends_on) - known_ids
            if unknown:
                missing = ", ".join(sorted(unknown))
                raise ValueError(f"unknown dependency ids: {missing}")

        if self.steps and self.current_step >= len(self.steps):
            raise ValueError("current_step is out of range for plan steps")

        return self
