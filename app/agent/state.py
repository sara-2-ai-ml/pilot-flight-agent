"""Centralized AgentState — single source of truth for agent sessions."""

from typing import Protocol
from uuid import uuid4

from pydantic import BaseModel, Field

from app.models.agent import Language, ReflectionRecord, ToolCallRecord
from app.models.booking import BookingState
from app.models.flight import FlightSearchState
from app.models.planning import Plan


class AgentState(BaseModel):
    """Full session state for one conversation."""

    conversation_id: str
    trace_id: str
    user_message: str = ""
    language: Language = Language.UNKNOWN
    user_context: dict[str, str] = Field(default_factory=dict)
    current_intent: str | None = None
    plan: Plan = Field(default_factory=Plan)
    flight_search: FlightSearchState = Field(default_factory=FlightSearchState)
    booking: BookingState = Field(default_factory=BookingState)
    tool_history: list[ToolCallRecord] = Field(default_factory=list)
    reflection_history: list[ReflectionRecord] = Field(default_factory=list)
    pending_approval: dict[str, object] | None = None
    iteration_count: int = 0
    llm_call_count: int = 0
    token_usage: int = 0
    step_retry_counts: dict[str, int] = Field(default_factory=dict)
    replan_count: int = 0
    pending_question: str | None = None

    @classmethod
    def new(cls, *, conversation_id: str, trace_id: str) -> "AgentState":
        return cls(conversation_id=conversation_id, trace_id=trace_id)


class StateStore(Protocol):
    def get(self, conversation_id: str) -> AgentState | None: ...

    def save(self, state: AgentState) -> None: ...

    def clear(self) -> None: ...


class InMemoryStateStore:
    """Session store for development and tests."""

    def __init__(self) -> None:
        self._sessions: dict[str, AgentState] = {}

    def get(self, conversation_id: str) -> AgentState | None:
        stored = self._sessions.get(conversation_id)
        if stored is None:
            return None
        return stored.model_copy(deep=True)

    def save(self, state: AgentState) -> None:
        self._sessions[state.conversation_id] = state.model_copy(deep=True)

    def clear(self) -> None:
        self._sessions.clear()


_default_store = InMemoryStateStore()


def get_state_store() -> InMemoryStateStore:
    return _default_store


def new_conversation_id() -> str:
    return uuid4().hex


def detect_language(message: str) -> Language:
    """Minimal language hint until intent understanding (Phase 2)."""
    lowered = message.lower()
    albanian_hints = ("fluturim", "rezervo", "nga", "per", "për", "dëshiroj", "desha")
    if any(hint in lowered for hint in albanian_hints):
        return Language.SQ
    return Language.EN


def update_from_user_message(
    state: AgentState,
    *,
    user_message: str,
    trace_id: str,
) -> AgentState:
    """Apply the current user turn to session state."""
    state.trace_id = trace_id
    state.user_message = user_message
    state.language = detect_language(user_message)
    if state.pending_question is not None:
        state.pending_question = None
    return state


def create_state_for_turn(
    *,
    conversation_id: str,
    trace_id: str,
    user_message: str,
) -> AgentState:
    """Create a new session state from an incoming user message."""
    state = AgentState.new(conversation_id=conversation_id, trace_id=trace_id)
    return update_from_user_message(state, user_message=user_message, trace_id=trace_id)
