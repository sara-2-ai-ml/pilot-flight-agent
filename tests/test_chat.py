"""Chat endpoint tests — Phase 0.5, Phase 11.7."""

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from app.agent.state import get_state_store
from app.config import Settings
from app.main import app, create_app
from app.models.agent import EvaluationStatus
from app.models.booking import BookingStatus
from app.models.planning import PlanStatus, StepStatus


def _booking_count(db_path: str) -> int:
    if not Path(db_path).exists():
        return 0
    with sqlite3.connect(db_path) as conn:
        try:
            return int(conn.execute("SELECT COUNT(*) FROM bookings").fetchone()[0])
        except sqlite3.OperationalError:
            return 0


def _mock_app_client(tmp_path) -> tuple[TestClient, Settings]:
    db_path = tmp_path / "bookings.db"
    settings = Settings(
        flight_api_use_mock=True,
        planner_use_mock=True,
        nlu_use_mock=True,
        booking_db_path=str(db_path),
    )
    return TestClient(create_app(settings)), settings


def test_chat_returns_trace_id(tmp_path) -> None:
    client, _settings = _mock_app_client(tmp_path)
    response = client.post("/chat", json={"message": "Find flights TIA to FRA on 2025-09-15"})

    assert response.status_code == 200
    body = response.json()
    assert len(body["trace_id"]) == 32
    assert len(body["conversation_id"]) == 32
    assert "Found 3 mock flights from TIA to FRA" in body["message"]


def test_chat_reuses_conversation_id() -> None:
    client = TestClient(app)
    conversation_id = "abc123"

    response = client.post(
        "/chat",
        json={"message": "Hello", "conversation_id": conversation_id},
    )

    assert response.status_code == 200
    assert response.json()["conversation_id"] == conversation_id


def test_chat_persists_state_across_requests(tmp_path) -> None:
    client, _settings = _mock_app_client(tmp_path)
    conversation_id = "conv-persist"

    first = client.post(
        "/chat",
        json={
            "message": "Find flights TIA to FRA on 2025-09-15",
            "conversation_id": conversation_id,
        },
    )
    second = client.post(
        "/chat",
        json={"message": "Second", "conversation_id": conversation_id},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert "Found 3 mock" in first.json()["message"]
    assert "LH001" in first.json()["message"]
    assert "Booking approval required" not in second.json()["message"]
    assert "Stub executed" not in second.json()["message"]


def test_chat_rejects_empty_message() -> None:
    client = TestClient(app)
    response = client.post("/chat", json={"message": ""})

    assert response.status_code == 422


def test_chat_returns_graceful_message_on_agent_failure() -> None:
    from unittest.mock import patch

    from app.agent.loop import run_chat

    client = TestClient(app)

    with patch(
        "app.api.chat.run_chat",
        return_value=(
            type("State", (), {"conversation_id": "conv-fail", "iteration_count": 1})(),
            "I couldn't complete this step after several attempts.",
        ),
    ):
        response = client.post("/chat", json={"message": "Find flights TIA to FRA"})

    assert response.status_code == 200
    body = response.json()
    assert body["message"] == "I couldn't complete this step after several attempts."
    assert "Traceback" not in body["message"]
    assert len(body["trace_id"]) == 32


def test_chat_e2e_mock_pipeline_search_validate_hitl() -> None:
    client = TestClient(app)
    conversation_id = "conv-e2e-pipeline"

    response = client.post(
        "/chat",
        json={
            "message": "Book flights TIA to FRA on 2025-09-15",
            "conversation_id": conversation_id,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["trace_id"]) == 32
    assert body["conversation_id"] == conversation_id
    assert body["trace_id"] == response.headers["X-Trace-Id"]
    assert "Found 3 mock flights from TIA to FRA" in body["message"]
    assert "Selected flight LH001" in body["message"]
    assert "Booking approval required" in body["message"]
    assert body["pending_approval"] is not None
    assert body["pending_approval"]["flight"]["id"] == "LH001"
    assert body.get("debug") is None

    state = get_state_store().get(conversation_id)
    assert state is not None
    assert state.plan.status == PlanStatus.IN_PROGRESS
    assert state.plan.steps[0].status == StepStatus.COMPLETED
    assert state.plan.steps[1].status == StepStatus.COMPLETED
    assert state.plan.steps[2].status == StepStatus.IN_PROGRESS
    assert len(state.flight_search.results) == 3
    assert state.flight_search.selected_option_id == "LH001"
    assert state.booking.booking_id is None
    assert len(state.tool_history) == 3
    assert len(state.reflection_history) == 2
    assert all(record.status == EvaluationStatus.CONTINUE for record in state.reflection_history)


def test_chat_e2e_mock_full_journey_confirm_and_follow_up(tmp_path) -> None:
    client, settings = _mock_app_client(tmp_path)
    conversation_id = "conv-e2e-journey"

    chat = client.post(
        "/chat",
        json={
            "message": "Book flights TIA to FRA on 2025-09-15 for Ana Krasniqi",
            "conversation_id": conversation_id,
        },
    )
    assert chat.status_code == 200
    assert chat.json()["pending_approval"] is not None
    assert chat.json()["pending_approval"]["passenger"] == "Ana Krasniqi"
    assert _booking_count(settings.booking_db_path) == 0

    confirm = client.post("/approvals/confirm", json={"conversation_id": conversation_id})
    assert confirm.status_code == 200
    confirm_body = confirm.json()
    assert confirm_body["success"] is True
    assert "Created booking BK-" in confirm_body["message"]
    assert _booking_count(settings.booking_db_path) == 1

    state = get_state_store().get(conversation_id)
    assert state is not None
    assert state.plan.status == PlanStatus.COMPLETED
    assert state.booking.booking_id is not None
    assert state.booking.status == BookingStatus.PENDING
    assert state.pending_approval is None

    follow_up = client.post(
        "/chat",
        json={
            "message": "Thanks, what is my booking status?",
            "conversation_id": conversation_id,
        },
    )
    assert follow_up.status_code == 200
    follow_body = follow_up.json()
    assert follow_body.get("pending_approval") is None
    assert "ready to help" in follow_body["message"].lower()

    persisted = get_state_store().get(conversation_id)
    assert persisted is not None
    assert persisted.iteration_count == 2
    assert persisted.booking.booking_id is not None


def test_chat_e2e_mock_ask_user_pauses_plan() -> None:
    client = TestClient(app)
    conversation_id = "conv-e2e-ask"

    response = client.post(
        "/chat",
        json={
            "message": "Find the cheapest flight TIA to FRA on 2025-09-15",
            "conversation_id": conversation_id,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body.get("pending_approval") is None
    assert "schedule" in body["message"].lower()

    state = get_state_store().get(conversation_id)
    assert state is not None
    assert state.pending_question is not None
    assert state.plan.status == PlanStatus.COMPLETED
    assert state.plan.steps[0].status == StepStatus.COMPLETED
    assert state.reflection_history[-1].status == EvaluationStatus.ASK_USER


def test_chat_e2e_mock_cancel_flow(tmp_path) -> None:
    client, settings = _mock_app_client(tmp_path)
    conversation_id = "conv-e2e-cancel"

    chat = client.post(
        "/chat",
        json={
            "message": "Book flights TIA to FRA on 2025-09-15",
            "conversation_id": conversation_id,
        },
    )
    assert chat.status_code == 200
    assert chat.json()["pending_approval"] is not None

    cancel = client.post("/approvals/cancel", json={"conversation_id": conversation_id})
    assert cancel.status_code == 200
    assert cancel.json()["success"] is True
    assert cancel.json()["message"] == "Booking request cancelled."
    assert _booking_count(settings.booking_db_path) == 0

    state = get_state_store().get(conversation_id)
    assert state is not None
    assert state.pending_approval is None
    assert state.plan.status == PlanStatus.COMPLETED
    assert state.plan.steps[2].status == StepStatus.SKIPPED
    assert state.booking.booking_id is None


def test_chat_e2e_multi_turn_preserves_completed_booking(tmp_path) -> None:
    client, settings = _mock_app_client(tmp_path)
    conversation_id = "conv-e2e-multi"

    client.post(
        "/chat",
        json={
            "message": "Book flights TIA to FRA on 2025-09-15",
            "conversation_id": conversation_id,
        },
    )
    client.post("/approvals/confirm", json={"conversation_id": conversation_id})

    before = get_state_store().get(conversation_id)
    assert before is not None
    booking_id = before.booking.booking_id

    second = client.post(
        "/chat",
        json={"message": "Any updates?", "conversation_id": conversation_id},
    )

    assert second.status_code == 200
    assert "Stub executed" not in second.json()["message"]
    assert "Found 3 mock" not in second.json()["message"]

    after = get_state_store().get(conversation_id)
    assert after is not None
    assert after.booking.booking_id == booking_id
    assert after.plan.status == PlanStatus.COMPLETED
    assert _booking_count(settings.booking_db_path) == 1


def test_chat_e2e_greeting_asks_for_route() -> None:
    client = TestClient(app)
    conversation_id = "conv-e2e-greeting"

    response = client.post(
        "/chat",
        json={"message": "hi", "conversation_id": conversation_id},
    )

    assert response.status_code == 200
    body = response.json()
    assert "flying from" in body["message"].lower() or "Where" in body["message"]
    assert "TIA to FRA" not in body["message"]
    assert "couldn't complete" not in body["message"].lower()

    state = get_state_store().get(conversation_id)
    assert state is not None
    assert state.pending_question is not None
    assert state.plan.steps == []
