"""FastAPI application tests."""

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app, create_app


def test_create_app_uses_settings() -> None:
    settings = Settings(app_name="Test Pilot Agent", debug=True)
    test_app = create_app(settings=settings)

    assert test_app.title == "Test Pilot Agent"
    assert test_app.state.settings is settings


def test_app_starts_without_crash() -> None:
    client = TestClient(app)
    assert client.app.title == "Pilot Flight Agent"
