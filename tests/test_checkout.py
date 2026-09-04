"""Mock checkout API tests."""

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_mock_checkout_completes_booking(tmp_path) -> None:
    settings = Settings(
        flight_api_use_mock=True,
        planner_use_mock=True,
        nlu_use_mock=True,
        booking_db_path=str(tmp_path / "bookings.db"),
    )
    client = TestClient(create_app(settings))
    conversation_id = "conv-checkout"

    chat = client.post(
        "/chat",
        json={"message": "Book flights TIA to FRA on 2025-09-15", "conversation_id": conversation_id},
    )
    assert chat.status_code == 200
    assert chat.json()["pending_approval"] is not None

    checkout = client.post(
        "/checkout/complete",
        json={
            "conversation_id": conversation_id,
            "cardholder_name": "Jane Doe",
            "card_number": "4242424242424242",
            "expiry": "12/28",
            "cvc": "123",
        },
    )
    assert checkout.status_code == 200
    body = checkout.json()
    assert body["success"] is True
    assert body["booking_id"].startswith("BK-")
    assert "4242" in body["message"]
    assert "Booking confirmed" in body["message"]

    pending = client.get("/approvals/pending", params={"conversation_id": conversation_id})
    assert pending.json()["pending_approval"] is None


def test_mock_checkout_rejects_short_card(tmp_path) -> None:
    settings = Settings(
        flight_api_use_mock=True,
        planner_use_mock=True,
        nlu_use_mock=True,
        booking_db_path=str(tmp_path / "bookings.db"),
    )
    client = TestClient(create_app(settings))
    conversation_id = "conv-checkout-bad"

    client.post(
        "/chat",
        json={"message": "Book flights TIA to FRA on 2025-09-15", "conversation_id": conversation_id},
    )

    checkout = client.post(
        "/checkout/complete",
        json={
            "conversation_id": conversation_id,
            "cardholder_name": "Jane Doe",
            "card_number": "1234",
            "expiry": "12/28",
            "cvc": "123",
        },
    )
    assert checkout.status_code in {400, 422}
