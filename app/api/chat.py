"""Chat endpoint — POST /chat."""

from fastapi import APIRouter, HTTPException, Request

from app.agent.loop import run_chat
from app.core.cost import build_cost_debug_payload, session_cost
from app.core.logging import get_logger
from app.core.metrics import session_metrics
from app.core.observability import log_extra
from app.core.tracing import generate_trace_id, get_trace_id
from app.guardrails.chain import run_inbound_chat_guards, run_outbound_guards
from app.guardrails.input_guard import InputGuardError
from app.models.agent import ChatRequest, ChatResponse

router = APIRouter(tags=["chat"])
logger = get_logger("api.chat")


@router.post("/chat", response_model=ChatResponse, response_model_exclude_none=True)
def chat(request: ChatRequest, http_request: Request) -> ChatResponse:
    trace_id = get_trace_id() or generate_trace_id()
    settings = http_request.app.state.settings
    try:
        user_message = run_inbound_chat_guards(
            request.message,
            request.conversation_id,
            settings=settings,
        )
    except InputGuardError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    state, message = run_chat(
        user_message=user_message,
        trace_id=trace_id,
        conversation_id=request.conversation_id,
        settings=settings,
    )

    metrics = session_metrics(state)
    cost = session_cost(state)
    logger.info(
        "chat_response",
        extra=log_extra(
            trace_id=trace_id,
            conversation_id=state.conversation_id,
            event="chat_response",
            iteration_count=metrics.iteration_count,
            tool_call_count=metrics.tool_call_count,
            llm_call_count=cost.llm_call_count,
            token_usage=cost.token_usage,
        ),
    )

    debug = None
    if settings.debug:
        debug = {"cost": build_cost_debug_payload(session=cost)}

    return ChatResponse(
        trace_id=trace_id,
        conversation_id=state.conversation_id,
        message=run_outbound_guards(message, settings=settings),
        pending_approval=getattr(state, "pending_approval", None),
        debug=debug,
    )
