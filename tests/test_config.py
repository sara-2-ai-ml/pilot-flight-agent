"""Configuration tests."""

import os

from app.config import Settings, ToolsMode, get_settings


def test_settings_defaults() -> None:
    settings = Settings()
    assert settings.app_name == "Pilot Flight Agent"
    assert settings.tools_mode == ToolsMode.DIRECT
    assert settings.flight_api_use_mock is True
    assert settings.max_iterations == 8


def test_get_settings_is_cached() -> None:
    get_settings.cache_clear()
    assert get_settings() is get_settings()


def test_dotenv_overrides_shell_nlu_use_mock(monkeypatch) -> None:
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("NLU_USE_MOCK", "true")
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.nlu_use_mock is False
    assert os.environ.get("NLU_USE_MOCK") == "false"
    get_settings.cache_clear()
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "tests/test_config.py::test_dotenv_overrides_shell_nlu_use_mock (call)")
