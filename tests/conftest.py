"""Shared pytest fixtures."""

import pytest

from app.agent.state import get_state_store
from app.agent.workers import reset_worker_registry
from app.config import get_settings
from app.tools.adapters import clear_tool_adapter_cache


@pytest.fixture(autouse=True)
def force_mock_llm_for_tests(monkeypatch) -> None:
    monkeypatch.setenv("NLU_USE_MOCK", "true")
    monkeypatch.setenv("PLANNER_USE_MOCK", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def reset_rate_limits() -> None:
    from app.guardrails.rate_limit import reset_rate_limiter

    reset_rate_limiter()
    yield
    reset_rate_limiter()


@pytest.fixture(autouse=True)
def reset_circuit_breakers() -> None:
    from app.core.circuit_breaker import reset_circuit_breaker

    reset_circuit_breaker()
    yield
    reset_circuit_breaker()


@pytest.fixture(autouse=True)
def clear_state_store() -> None:
    get_state_store().clear()
    yield
    get_state_store().clear()


@pytest.fixture(autouse=True)
def isolated_booking_db(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "bookings.db"
    monkeypatch.setenv("BOOKING_DB_PATH", str(db_path))
    get_settings.cache_clear()
    clear_tool_adapter_cache()
    reset_worker_registry()
    yield
    get_settings.cache_clear()
    clear_tool_adapter_cache()
    reset_worker_registry()
