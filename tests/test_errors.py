"""Error handling tests — Phase 3.7."""

from fastapi.testclient import TestClient

from app.core.errors import AgentFailure, DEFAULT_USER_ERROR_MESSAGE
from app.main import create_app


def test_agent_failure_handler_returns_controlled_500() -> None:
    app = create_app()

    @app.get("/boom")
    def boom() -> None:
        raise AgentFailure(
            message="I couldn't complete your request.",
            trace_id="trace123",
            issue="internal detail",
        )

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/boom")

    assert response.status_code == 500
    body = response.json()
    assert body["detail"] == "I couldn't complete your request."
    assert body["trace_id"] == "trace123"
    assert "internal detail" not in body["detail"]


def test_unhandled_exception_returns_safe_message_without_traceback() -> None:
    app = create_app()

    @app.get("/crash")
    def crash() -> None:
        raise RuntimeError("secret database password leaked")

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/crash")

    assert response.status_code == 500
    body = response.json()
    assert body["detail"] == DEFAULT_USER_ERROR_MESSAGE
    assert "password" not in body["detail"]
    assert "trace_id" in body
