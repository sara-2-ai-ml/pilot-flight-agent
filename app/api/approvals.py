"""Human approval endpoints — POST /approvals/confirm and /approvals/cancel."""

from fastapi import APIRouter, HTTPException, Query, Request

from app.agent.approval_flow import ApprovalFlowError, run_cancel_approval, run_confirm_approval
from app.agent.state import get_state_store
from app.core.logging import get_logger
from app.core.tracing import generate_trace_id, get_trace_id
from app.guardrails.approval import parse_booking_approval
from app.guardrails.chain import run_inbound_approval_guards, run_outbound_guards
from app.models.agent import ApprovalRequest, ApprovalResponse
from app.models.approval import ApprovalPendingResponse, BookingApprovalPayload

router = APIRouter(prefix="/approvals", tags=["approvals"])
logger = get_logger("api.approvals")


def _parse_pending_payload(payload: dict[str, object] | None) -> BookingApprovalPayload | None:
    if payload is None:
        return None
    return parse_booking_approval(payload)


@router.get("/pending", response_model=ApprovalPendingResponse)
def get_pending_approval(
    conversation_id: str = Query(min_length=1),
) -> ApprovalPendingResponse:
    trace_id = get_trace_id() or generate_trace_id()
    state = get_state_store().get(conversation_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Conversation '{conversation_id}' not found.")

    return ApprovalPendingResponse(
        trace_id=trace_id,
        conversation_id=conversation_id,
        pending_approval=_parse_pending_payload(state.pending_approval),
    )


@router.post("/confirm", response_model=ApprovalResponse)
def confirm_approval(request: ApprovalRequest, http_request: Request) -> ApprovalResponse:
    trace_id = get_trace_id() or generate_trace_id()
    settings = http_request.app.state.settings
    run_inbound_approval_guards(request.conversation_id, settings=settings)
    try:
        state, message, success = run_confirm_approval(
            conversation_id=request.conversation_id,
            trace_id=trace_id,
        )
    except ApprovalFlowError as exc:
        detail = str(exc)
        status_code = 404 if "not found" in detail.lower() else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc

    logger.info(
        "approval_confirmed",
        extra={
            "trace_id": trace_id,
            "conversation_id": state.conversation_id,
            "event": "approval_confirmed",
            "success": success,
        },
    )

    return ApprovalResponse(
        trace_id=trace_id,
        conversation_id=state.conversation_id,
        message=run_outbound_guards(message, settings=settings),
        success=success,
    )


@router.post("/cancel", response_model=ApprovalResponse)
def cancel_approval(request: ApprovalRequest, http_request: Request) -> ApprovalResponse:
    trace_id = get_trace_id() or generate_trace_id()
    settings = http_request.app.state.settings
    run_inbound_approval_guards(request.conversation_id, settings=settings)
    try:
        state, message, success = run_cancel_approval(
            conversation_id=request.conversation_id,
            trace_id=trace_id,
        )
    except ApprovalFlowError as exc:
        detail = str(exc)
        status_code = 404 if "not found" in detail.lower() else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc

    logger.info(
        "approval_cancelled",
        extra={
            "trace_id": trace_id,
            "conversation_id": state.conversation_id,
            "event": "approval_cancelled",
            "success": success,
        },
    )

    return ApprovalResponse(
        trace_id=trace_id,
        conversation_id=state.conversation_id,
        message=run_outbound_guards(message, settings=settings),
        success=success,
    )
