"""Evaluation dataset models — Phase 12.1."""

from enum import Enum

from pydantic import BaseModel, Field, model_validator


class EvalCategory(str, Enum):
    """High-level bucket for grouping eval cases."""

    HAPPY_PATH = "happy_path"
    AMBIGUOUS = "ambiguous"
    INJECTION = "injection"
    HITL = "hitl"
    SAFETY = "safety"


class EvalAction(str, Enum):
    """User or operator action simulated by the eval runner."""

    CHAT = "chat"
    CONFIRM = "confirm"
    CANCEL = "cancel"


class ExpectedOutcome(str, Enum):
    """Terminal outcome the eval runner should observe."""

    COMPLETED = "completed"
    PENDING_APPROVAL = "pending_approval"
    ASK_USER = "ask_user"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"
    FAILED = "failed"


class EvalTurn(BaseModel):
    """One step in a multi-turn eval scenario."""

    action: EvalAction = EvalAction.CHAT
    message: str | None = Field(
        default=None,
        description="Required for chat turns; omitted for confirm/cancel",
    )

    @model_validator(mode="after")
    def validate_message_for_action(self) -> "EvalTurn":
        if self.action == EvalAction.CHAT and self.message is None:
            raise ValueError("chat turns require a message")
        return self


class EvalExpectations(BaseModel):
    """Assertions applied after executing all turns."""

    outcome: ExpectedOutcome
    http_status: int = Field(default=200, ge=100, le=599)
    message_contains: list[str] = Field(default_factory=list)
    message_not_contains: list[str] = Field(default_factory=list)
    pending_approval: bool | None = None
    plan_status: str | None = None
    booking_created: bool | None = None


class EvalCase(BaseModel):
    """Single eval scenario with turns and expected results."""

    id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)
    turns: list[EvalTurn] = Field(min_length=1)
    expectations: EvalExpectations


class EvalDataset(BaseModel):
    """One JSON dataset file grouping related eval cases."""

    category: EvalCategory
    description: str = Field(min_length=1)
    cases: list[EvalCase] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_case_ids(self) -> "EvalDataset":
        ids = [case.id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("case ids must be unique within a dataset file")
        return self
