"""Agent domain models — state, intent, evaluation."""

from enum import Enum

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, description="User message in Albanian or English")
    conversation_id: str | None = Field(
        default=None,
        description="Existing conversation id; a new one is created if omitted",
    )


class ChatResponse(BaseModel):
    trace_id: str
    conversation_id: str
    message: str
    pending_approval: dict[str, object] | None = None
    debug: dict[str, object] | None = Field(
        default=None,
        description="Optional diagnostics when DEBUG=true (includes LLM cost counters)",
    )


class ApprovalRequest(BaseModel):
    conversation_id: str = Field(min_length=1)


class ApprovalResponse(BaseModel):
    trace_id: str
    conversation_id: str
    message: str
    success: bool


class MockCheckoutRequest(BaseModel):
    conversation_id: str = Field(min_length=1)
    cardholder_name: str = Field(min_length=1, max_length=80)
    card_number: str = Field(min_length=13, max_length=24)
    expiry: str = Field(min_length=4, max_length=7)
    cvc: str = Field(min_length=3, max_length=4)


class MockCheckoutResponse(BaseModel):
    trace_id: str
    conversation_id: str
    message: str
    success: bool
    booking_id: str


class Language(str, Enum):
    EN = "en"
    SQ = "sq"
    UNKNOWN = "unknown"


class EvaluationStatus(str, Enum):
    CONTINUE = "continue"
    RETRY = "retry"
    REPLAN = "replan"
    ASK_USER = "ask_user"
    FAIL = "fail"


class EvaluationResult(BaseModel):
    """Structured outcome from the evaluator after a plan step or tool call."""

    status: EvaluationStatus
    issue: str | None = Field(
        default=None,
        description="Internal reason for retry, replan, ask_user, or fail",
    )
    message: str | None = Field(
        default=None,
        description="Optional user-facing explanation",
    )


class ToolCallRecord(BaseModel):
    """One worker/tool execution persisted on session state."""

    tool: str
    action: str
    status: str
    step_id: str | None = Field(
        default=None,
        description="Plan step that triggered the tool call",
    )
    trace_id: str | None = Field(
        default=None,
        description="Request trace id when the call was recorded",
    )
    message: str | None = Field(
        default=None,
        description="Worker result message when available",
    )
    error_code: str | None = Field(
        default=None,
        description="Stable worker error code when the call failed",
    )
    iteration: int | None = Field(
        default=None,
        ge=0,
        description="Session iteration count when the call was recorded",
    )


class ReflectionRecord(BaseModel):
    """One evaluator decision persisted on session state."""

    status: EvaluationStatus
    issue: str | None = None
    message: str | None = Field(
        default=None,
        description="User-facing explanation when applicable",
    )
    step_id: str | None = Field(
        default=None,
        description="Plan step that was evaluated",
    )
    trace_id: str | None = Field(
        default=None,
        description="Request trace id when the decision was recorded",
    )
    iteration: int | None = Field(
        default=None,
        ge=0,
        description="Session iteration count when the decision was recorded",
    )
