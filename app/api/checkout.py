"""Mock checkout — card form then confirm booking."""

from fastapi import APIRouter, HTTPException, Request

from app.agent.approval_flow import ApprovalFlowError, run_confirm_approval
from app.core.logging import get_logger
from app.core.tracing import generate_trace_id, get_trace_id
from app.guardrails.chain import run_inbound_approval_guards, run_outbound_guards
from app.models.agent import MockCheckoutRequest, MockCheckoutResponse

router = APIRouter(prefix="/checkout", tags=["checkout"])
logger = get_logger("api.checkout")


def _card_last4(card_number: str) -> str:
    digits = "".join(ch for ch in card_number if ch.isdigit())
    if len(digits) < 13:
        raise HTTPException(
            status_code=400,
            detail="Enter a valid mock card number (at least 13 digits).",
        )
    return digits[-4:]


@router.post("/complete", response_model=MockCheckoutResponse)
def complete_mock_checkout(
    request: MockCheckoutRequest,
    http_request: Request,
) -> MockCheckoutResponse:
    """Accept mock payment details and finalize the pending booking."""
    trace_id = get_trace_id() or generate_trace_id()
    settings = http_request.app.state.settings
    run_inbound_approval_guards(request.conversation_id, settings=settings)

    if not request.cardholder_name.strip():
        raise HTTPException(status_code=400, detail="Cardholder name is required.")

    card_last4 = _card_last4(request.card_number)

    try:
        state, message, success = run_confirm_approval(
            conversation_id=request.conversation_id,
            trace_id=trace_id,
            settings=settings,
        )
    except ApprovalFlowError as exc:
        detail = str(exc)
        status_code = 404 if "not found" in detail.lower() else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc

    if not success:
        raise HTTPException(status_code=400, detail=message)

    booking_id = state.booking.booking_id or ""
    logger.info(
        "mock_checkout_completed",
        extra={
            "trace_id": trace_id,
            "conversation_id": state.conversation_id,
            "event": "mock_checkout_completed",
            "booking_id": booking_id,
            "card_last4": card_last4,
        },
    )

    final_message = (
        f"Payment received (mock ····{card_last4}). "
        f"Booking confirmed — reference {booking_id}."
    )

    return MockCheckoutResponse(
        trace_id=trace_id,
        conversation_id=state.conversation_id,
        message=run_outbound_guards(final_message, settings=settings),
        success=True,
        booking_id=booking_id,
    )
